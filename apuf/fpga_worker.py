import argparse
import gc
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import serial

from apuf import (
    execute_with_retry,
    get_db_connection,
    initialize_database,
    setup_worker_logger,
)

logger = None


def file_md5(path: Path, chunk_size=1024 * 1024) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_args():
    parser = argparse.ArgumentParser(description="APUF Data Collection Worker")
    # Global Arguments (Required for all commands)
    parser.add_argument("--log_file", type=Path, help="Path to write log output")
    parser.add_argument(
        "--serial_port",
        type=str,
        required=True,
        help="Serial port (use /dev/serial/by-id/...)",
    )
    parser.add_argument(
        "--device",
        type=str,
        required=True,
        help="Device id to be stored in the db. Should be {prefix}-{serial_id}",
    )
    parser.add_argument("--baud", type=int, default=1000000, help="UART Baud rate")
    parser.add_argument(
        "--stages", type=int, required=True, help="Number of PUF stages"
    )
    parser.add_argument(
        "--slice_loc",
        type=str,
        required=True,
        help="Physical slice location",
    )
    parser.add_argument(
        "--placement_variant",
        type=str,
        default="lr_abcd",
        help="Physical placement variant used to build the programmed bitstream",
    )
    parser.add_argument(
        "--placement_gap",
        type=int,
        default=1,
        help="Column gap used by the physical placement generator",
    )
    parser.add_argument(
        "--placement_offset",
        type=int,
        default=0,
        help="Vertical row offset used by the physical placement generator",
    )

    # Define Subparsers
    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Worker commands"
    )

    # Command: Collect (Normal Data Collection)
    collect_parser = subparsers.add_parser("study", help="Run normal data collection")
    collect_parser.add_argument(
        "--db_dir",
        type=str,
        required=True,
        help="Path to the directory to store the SQLite DBs",
    )
    collect_parser.add_argument(
        "--samples",
        type=int,
        default=1,
        help="Number of times to replay the full challenge file",
    )
    collect_parser.add_argument(
        "--chunk_size", type=int, default=1000, help="Number of challenges at a time"
    )
    collect_parser.add_argument(
        "--challenges_file", type=Path, required=True, help="Path to .npy challenges"
    )
    collect_parser.add_argument(
        "--take_lsb",
        action="store_true",
        help="Chunk the challenges from the left (LSBs) instead of the right (MSB). Defaults to MSB",
    )

    return parser.parse_args()


def get_challenges(args):
    if not args.challenges_file.exists():
        raise FileNotFoundError(f"Challenge file not found: {args.challenges_file}")

    challenges = np.load(args.challenges_file)

    if challenges.ndim != 2:
        raise ValueError(f"Challenges must be a 2D array, got shape {challenges.shape}")

    return challenges


def run_worker():
    global logger
    args = get_args()

    logger = setup_worker_logger(args.log_file)

    device = args.device
    con = None
    ser = None
    success = False

    CHUNK_SIZE = args.chunk_size

    try:
        ser = serial.Serial(args.serial_port, args.baud, timeout=10)
        logger.info(f"Connected to {device} at {args.baud} baud.")

        master_challenges = get_challenges(args)
        challenge_md5 = file_md5(args.challenges_file)
        count, n_bits = master_challenges.shape

        if args.stages > n_bits:
            raise ValueError(
                f"Requested {args.stages} stages, but challenge source only has "
                f"{n_bits} bits per challenge."
            )

        if args.take_lsb:
            # For ergodicity study
            bit_ids = np.arange(args.stages)
        else:
            bit_ids = np.arange(n_bits - args.stages, n_bits)

        Path(args.db_dir).mkdir(parents=True, exist_ok=True)
        db_path = Path(args.db_dir) / f"{args.device}.db"
        con = get_db_connection(db_path)
        cursor = con.cursor()
        initialize_database(con)

        cursor.execute(
            """
            INSERT OR IGNORE INTO studies (
                device_id, slice, stages, challenge_md5,
                placement_variant, placement_gap, placement_offset
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                args.device,
                args.slice_loc,
                args.stages,
                challenge_md5,
                args.placement_variant,
                args.placement_gap,
                args.placement_offset,
            ),
        )

        cursor.execute(
            """
            SELECT study_id FROM studies
            WHERE device_id=? AND slice=? AND stages=? AND challenge_md5=?
              AND placement_variant=? AND placement_gap=? AND placement_offset=?
        """,
            (
                args.device,
                args.slice_loc,
                args.stages,
                challenge_md5,
                args.placement_variant,
                args.placement_gap,
                args.placement_offset,
            ),
        )
        study_id = cursor.fetchone()[0]

        cursor.execute(
            "INSERT INTO acquisitions (study_id, started_at) VALUES (?, ?)",
            (study_id, datetime.now(timezone.utc).isoformat()),
        )
        acquisition_id = cursor.lastrowid

        for sample_id in range(args.samples):
            # Pre-allocate a byte buffer in RAM
            all_raw_resp = bytearray()

            # Stream all chunks at maximum UART speed (NO DB I/O allowed)
            for i in range(0, count, CHUNK_SIZE):
                chunk_end = min(i + CHUNK_SIZE, count)

                chunk_bits = master_challenges[i:chunk_end, bit_ids]
                chunk_bytes = np.packbits(
                    chunk_bits, axis=1, bitorder="little"
                ).tobytes()

                ser.write(chunk_bytes)

                # Optional: tiny 1ms delay if your USB hub still struggles with brownouts,
                # otherwise remove entirely for max speed.
                # time.sleep(0.001)

                current_chunk_size = chunk_end - i
                raw_resp = ser.read(current_chunk_size)

                if len(raw_resp) != current_chunk_size:
                    raise RuntimeError(
                        f"[{args.device}] Incomplete UART response: expected "
                        f"{current_chunk_size} bytes, received {len(raw_resp)}"
                    )

                all_raw_resp.extend(raw_resp)

            # Only interact with the database AFTER the rapid-fire stream finishes
            if len(all_raw_resp) == count:
                records = [
                    (acquisition_id, sample_id, idx, raw_byte & 0x01)
                    for idx, raw_byte in enumerate(all_raw_resp)
                ]

                execute_with_retry(
                    cursor,
                    """
                    INSERT INTO crps (acquisition_id, sample_id, challenge_id, response)
                    VALUES (?, ?, ?, ?)
                """,
                    records,
                )

                con.commit()
                logger.info(f"[{args.device}] Sample {sample_id} fully recorded")
            else:
                logger.error(
                    f"[{args.device}] Sample {sample_id} failed due to dropped bytes. DB entry skipped."
                )

            # Force SQLite memory structures and Python arrays to clear
            gc.collect()

        success = True
    except Exception:
        logger.exception(f"[{device}] Acquisition failed")
        if con is not None:
            con.rollback()
    finally:
        if con is not None:
            con.close()
        if ser is not None:
            ser.close()

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(run_worker())
