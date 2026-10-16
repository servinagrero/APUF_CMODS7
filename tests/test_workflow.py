import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from apuf import initialize_database
from scripts.export_csvs import export_csvs
from scripts.merge_dbs import merge_databases


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.data_directory = Path(self.temporary_directory.name)

    def _create_worker_database(self, name: str, device_id: str) -> Path:
        database = self.data_directory / name
        with sqlite3.connect(database) as connection:
            initialize_database(connection)
            connection.execute(
                """
                INSERT INTO studies (
                    study_id, device_id, slice, stages, challenge_md5,
                    placement_variant, placement_gap, placement_offset
                ) VALUES (1, ?, 'LEFT-LOWER-1', 64, 'checksum',
                          'decor_left2', 1, 0)
                """,
                (device_id,),
            )
            connection.execute(
                """
                INSERT INTO acquisitions (acquisition_id, study_id, started_at)
                VALUES (1, 1, '2026-01-01T00:00:00')
                """
            )
            connection.executemany(
                """
                INSERT INTO crps (
                    acquisition_id, challenge_id, sample_id, response
                ) VALUES (1, ?, 0, ?)
                """,
                ((0, 0), (1, 1)),
            )
        return database

    def test_merge_and_export_preserve_all_device_data(self):
        first = self._create_worker_database("device-a.db", "device-a")
        second = self._create_worker_database("device-b.db", "device-b")

        merged = merge_databases(self.data_directory)

        with sqlite3.connect(merged) as connection:
            counts = tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("studies", "acquisitions", "crps")
            )
        self.assertEqual(counts, (2, 2, 4))
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())

        raw_csv, summary_csv = export_csvs(merged)

        with raw_csv.open(newline="", encoding="utf-8") as csv_file:
            raw_rows = list(csv.DictReader(csv_file))
        with summary_csv.open(newline="", encoding="utf-8") as csv_file:
            summary_rows = list(csv.DictReader(csv_file))

        self.assertEqual(len(raw_rows), 4)
        self.assertEqual(len(summary_rows), 4)
        self.assertEqual(
            list(raw_rows[0]),
            [
                "challenge_id",
                "sample_id",
                "acquisition_id",
                "started_at",
                "device_id",
                "slice",
                "stages",
                "placement_variant",
                "placement_gap",
                "placement_offset",
                "response",
            ],
        )
        self.assertEqual(
            [row["device_id"] for row in raw_rows],
            ["device-a", "device-a", "device-b", "device-b"],
        )

    def test_existing_outputs_require_force(self):
        self._create_worker_database("device-a.db", "device-a")
        merged = merge_databases(self.data_directory)

        with self.assertRaises(FileExistsError):
            merge_databases(self.data_directory)

        export_csvs(merged)
        with self.assertRaises(FileExistsError):
            export_csvs(merged)


if __name__ == "__main__":
    unittest.main()
