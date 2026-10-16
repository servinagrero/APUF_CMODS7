import argparse
import concurrent.futures
import glob
import logging
import sqlite3
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from apuf import FPGADevice, discover_hardware, setup_master_logger

logger = setup_master_logger()


def launch_single_worker(device: FPGADevice, cmd: list):
    """Target function executed inside the ThreadPool."""
    result = subprocess.run(cmd)

    if result.returncode == 0:
        logger.info(f"{device.device_id} completed successfully.")
    else:
        logger.error(f"{device.device_id} crashed (Exit code: {result.returncode})")

    return result.returncode


def run_parallel_study_pool(
    command: str,
    devices: list[FPGADevice],
    params: dict,
    stages: int,
    slice_loc: str,
    max_active_nodes=4,
):
    placement_variant = params.get("placement_variant", "lr_abcd")
    placement_gap = int(params.get("placement_gap", 1))
    placement_offset = int(params.get("placement_offset", 0))
    placement_id = f"{placement_variant}_g{placement_gap}_o{placement_offset}"
    bitstream = f"build/{placement_id}/{slice_loc}_{stages}/top.bit"

    # Program all devices sequentially
    valid_devices = []
    all_programmed = True
    for dev in devices:
        if dev.program(bitstream):
            valid_devices.append(dev)
            time.sleep(0.01)
        else:
            all_programmed = False

    if not valid_devices:
        logger.error("No devices successfully programmed. Skipping this configuration.")
        return False

    logger.info(
        f"Starting study on {slice_loc} slice for {stages} stages using {placement_id}"
    )
    logger.info(f"Max concurrent writers: {max_active_nodes}")

    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_active_nodes
    ) as executor:
        futures = {}
        all_workers_succeeded = True

        for dev in valid_devices:
            worker_log_path = str(log_dir / f"{dev.device_id}.log")
            cmd = dev.build_worker_cmd(
                command, params, stages, slice_loc, str(worker_log_path)
            )

            future = executor.submit(launch_single_worker, dev, cmd)
            futures[future] = dev

        # Monitor completions
        for future in concurrent.futures.as_completed(futures):
            dev = futures[future]
            try:
                if future.result() != 0:
                    all_workers_succeeded = False
            except Exception as exc:
                logger.error(f"Execution exception for {dev.device_id}: {exc}")
                all_workers_succeeded = False

    return all_programmed and all_workers_succeeded


def get_args():
    parser = argparse.ArgumentParser(description="APUF Master Orchestrator")

    # Global Master Arguments
    parser.add_argument("--max_nodes", type=int, default=4, help="Max parallel devices")
    parser.add_argument("--config", default="config.toml", help="Path to TOML config")

    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Master commands"
    )

    # Command: Study
    study_parser = subparsers.add_parser("study", help="Run a specific study")
    study_parser.add_argument(
        "name", type=str, help="Name of the study defined in config"
    )

    # Command: Sensors
    subparsers.add_parser("sensors", help="Read the XADC sensors")

    return parser.parse_args()


def main():
    args = get_args()

    with open(args.config, "rb") as f:
        config = tomllib.load(f)

    # Isolate global parameters early
    params = config["global"].copy()

    valid_devices = discover_hardware(config["families"])
    if not valid_devices:
        logger.info("No devices found.")
        return 1
    logger.info(f"Found {len(valid_devices)} valid devices connected")

    if args.command == "sensors":
        for device in valid_devices:
            sensors = device.read_sensors()
            logger.info(sensors)
        return 0

    if args.command == "study":
        if args.name not in config["studies"]:
            logger.error(f"Error: Study '{args.name}' not found in config.")
            sys.exit(1)

        params.update(config["studies"][args.name])
        logger.info(f"Found {len(valid_devices)} devices. Starting study: {args.name}")
        all_configurations_succeeded = True

        for stages in params["stages"]:
            for slice_loc in params["slices"]:
                configuration_succeeded = run_parallel_study_pool(
                    args.command,
                    valid_devices,
                    params,
                    stages,
                    slice_loc,
                    max_active_nodes=args.max_nodes,
                )
                all_configurations_succeeded &= configuration_succeeded

        return 0 if all_configurations_succeeded else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
