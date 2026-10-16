import argparse
import csv
import sqlite3
import tempfile
from pathlib import Path


SUMMARY_QUERY = """
SELECT
    c.challenge_id,
    s.device_id,
    s.slice,
    s.stages,
    s.placement_variant,
    s.placement_gap,
    s.placement_offset,
    AVG(c.response) AS mean_response
FROM crps AS c
JOIN acquisitions AS a ON c.acquisition_id = a.acquisition_id
JOIN studies AS s ON a.study_id = s.study_id
GROUP BY
    s.device_id,
    s.slice,
    s.stages,
    s.placement_variant,
    s.placement_gap,
    s.placement_offset,
    c.challenge_id
ORDER BY
    s.device_id,
    s.slice,
    s.stages,
    s.placement_variant,
    s.placement_gap,
    s.placement_offset,
    c.challenge_id
"""

RAW_QUERY = """
SELECT
    c.challenge_id,
    c.sample_id,
    c.acquisition_id,
    a.started_at,
    s.device_id,
    s.slice,
    s.stages,
    s.placement_variant,
    s.placement_gap,
    s.placement_offset,
    c.response
FROM crps AS c
JOIN acquisitions AS a ON c.acquisition_id = a.acquisition_id
JOIN studies AS s ON a.study_id = s.study_id
ORDER BY
    s.device_id,
    s.slice,
    s.stages,
    s.placement_variant,
    s.placement_gap,
    s.placement_offset,
    c.acquisition_id,
    c.challenge_id,
    c.sample_id
"""


def _write_query(
    connection: sqlite3.Connection, query: str, output_dir: Path, prefix: str
) -> Path:
    cursor = connection.execute(query)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=output_dir,
        prefix=prefix,
        suffix=".tmp",
        delete=False,
    ) as temporary_file:
        writer = csv.writer(temporary_file)
        writer.writerow(column[0] for column in cursor.description)
        writer.writerows(cursor)
        return Path(temporary_file.name)


def export_csvs(
    database: Path, output_dir: Path | None = None, *, force: bool = False
) -> tuple[Path, Path]:
    database = database.resolve()
    if not database.is_file():
        raise ValueError(f"database does not exist: {database}")

    output_dir = (output_dir or database.parent).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_output = output_dir / "crps.csv"
    summary_output = output_dir / "crps_summary.csv"
    outputs = (raw_output, summary_output)
    existing = [output for output in outputs if output.exists()]
    if existing and not force:
        names = ", ".join(str(output) for output in existing)
        raise FileExistsError(f"output already exists: {names} (use --force)")

    temporary_paths: list[Path] = []
    try:
        database_uri = f"{database.as_uri()}?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as connection:
            temporary_paths.append(
                _write_query(connection, RAW_QUERY, output_dir, ".crps.csv.")
            )
            temporary_paths.append(
                _write_query(
                    connection, SUMMARY_QUERY, output_dir, ".crps_summary.csv."
                )
            )

        for temporary_path, output in zip(temporary_paths, outputs, strict=True):
            temporary_path.replace(output)
        temporary_paths.clear()
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)

    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export an APUF database to CSV")
    parser.add_argument("database", type=Path, help="merged SQLite database")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="destination directory (default: database directory)",
    )
    parser.add_argument(
        "--force", action="store_true", help="replace existing CSV files"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        raw_output, summary_output = export_csvs(
            args.database, args.output_dir, force=args.force
        )
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"error: {error}")
        return 1

    print(f"Exported {raw_output}")
    print(f"Exported {summary_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
