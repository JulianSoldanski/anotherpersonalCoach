import sqlite3
import unittest

from schema_web import ensure_web_tables


class TestSchemaWeb(unittest.TestCase):
    def test_ensure_web_tables(self):
        conn = sqlite3.connect(":memory:")
        ensure_web_tables(conn)
        conn.commit()
        row = conn.execute(
            "SELECT id FROM athlete_profile WHERE id = 1"
        ).fetchone()
        self.assertIsNotNone(row)
        conn.close()


if __name__ == "__main__":
    unittest.main()
