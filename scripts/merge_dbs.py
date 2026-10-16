import argparse
import logging
import sqlite3
import tempfile
from pathlib import Path

from apuf import initialize_database


logger = logging.getLogger(__name__)


def _worker_databases(db_dir: Path, output: Path) -> list[Path]:
    return [
        database
        for database in sorted(db_dir.glob("*.db"))
        if database != output and not database.name.endswith("_merged.db")
    ]


def _database_counts(connection: sqlite3.Connection) -> tuple[int, int, int]:
    return tuple(
        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("studies", "acquisitions", "crps")
    )


def merge_databases(
    db_dir: Path, output: Path | None = None, *, force: bool = False
) -> Path:
    db_dir = db_dir.resolve()
    if not db_dir.is_dir():
        raise ValueError(f"database directory does not exist: {db_dir}")

    output = (output or db_dir / f"{db_dir.name}_merged.db").resolve()
    if output.exists() and not force:
        raise FileExistsError(f"output already exists: {output} (use --force)")

    worker_databases = _worker_databases(db_dir, output)
    if not worker_databases:
        raise ValueError(f"no worker databases found in {db_dir}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    connection: sqlite3.Connection | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        connection = sqlite3.connect(temporary_path)
        connection.execute("PRAGMA foreign_keys = ON")
        initialize_database(connection)

        for worker_database in worker_databases:
            logger.info("Merging %s", worker_database)
            connection.execute(
                "ATTACH DATABASE ? AS worker_db", (str(worker_database),)
            )
            try:
                study_offset = connection.execute(
                    "SELECT COALESCE(MAX(study_id), 0) FROM main.studies"
                ).fetchone()[0]
                acquisition_offset = connection.execute(
                    "SELECT COALESCE(MAX(acquisition_id), 0) FROM main.acquisitions"
                ).fetchone()[0]

                connection.execute(
                    """
                    INSERT INTO main.studies (
                        study_id, device_id, slice, stages, challenge_md5,
                        placement_variant, placement_gap, placement_offset,
                        created_at
                    )
                    SELECT
                        study_id + ?, device_id, slice, stages, challenge_md5,
                        placement_variant, placement_gap, placement_offset,
                        created_at
                    FROM worker_db.studies
                    """,
                    (study_offset,),
                )
                connection.execute(
                    """
                    INSERT INTO main.acquisitions (
                        acquisition_id, study_id, started_at
                    )
                    SELECT acquisition_id + ?, study_id + ?, started_at
                    FROM worker_db.acquisitions
                    """,
                    (acquisition_offset, study_offset),
                )
                connection.execute(
                    """
                    INSERT INTO main.crps (
                        acquisition_id, challenge_id, sample_id, response
                    )
                    SELECT acquisition_id + ?, challenge_id, sample_id, response
                    FROM worker_db.crps
                    """,
                    (acquisition_offset,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.execute("DETACH DATABASE worker_db")

        counts = _database_counts(connection)
        connection.close()
        connection = None
        temporary_path.replace(output)
        temporary_path = None
    finally:
        if connection is not None:
            connection.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    logger.info(
        "Merged %d databases into %s (%d studies, %d acquisitions, %d CRPs)",
        len(worker_databases),
        output,
        *counts,
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge per-device APUF databases")
    parser.add_argument(
        "--db-dir",
        "--db_dir",
        dest="db_dir",
        type=Path,
        required=True,
        help="directory containing per-device SQLite databases",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="output database (default: <db-dir>/<directory-name>_merged.db)",
    )
    parser.add_argument(
        "--force", action="store_true", help="replace an existing output database"
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    try:
        merge_databases(args.db_dir, args.output, force=args.force)
    except (OSError, sqlite3.Error, ValueError) as error:
        logger.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
