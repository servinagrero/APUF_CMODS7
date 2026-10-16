import sqlite3
import unittest

from apuf import initialize_database


class DatabaseTests(unittest.TestCase):
    def test_initialize_database_creates_expected_tables(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)

        initialize_database(connection)

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertEqual(tables, {"studies", "acquisitions", "crps"})


if __name__ == "__main__":
    unittest.main()
