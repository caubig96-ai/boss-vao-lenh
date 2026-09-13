import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from database import Database


class PersistenceTests(unittest.TestCase):
    @staticmethod
    def _read_balance(path: str) -> str:
        # sqlite3.Connection.__exit__ only commits/rolls back; it does NOT close
        # the OS file handle. On Windows an unclosed handle makes
        # TemporaryDirectory cleanup fail with WinError 32.
        with closing(sqlite3.connect(path)) as conn:
            return conn.execute(
                "SELECT value FROM settings WHERE key='current_balance'"
            ).fetchone()[0]

    def test_legacy_windows_database_is_migrated_once(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_dir = os.path.join(directory, "data")
            os.makedirs(legacy_dir, exist_ok=True)
            legacy = os.path.join(legacy_dir, "bot.db")
            with closing(sqlite3.connect(legacy)) as conn:
                conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                conn.execute("INSERT INTO settings(key,value) VALUES('current_balance','123.45')")
                conn.commit()

            target = os.path.join(directory, "persistent", "bot.db")
            db = Database(target)
            with patch("database.os.name", "nt"), patch("database.os.getcwd", return_value=directory):
                db._migrate_legacy_windows_database()

            self.assertTrue(os.path.isfile(target))
            self.assertEqual(self._read_balance(target), "123.45")

            # Nếu target đã tồn tại thì lần sau không ghi đè dữ liệu mới.
            with closing(sqlite3.connect(target)) as conn:
                conn.execute("UPDATE settings SET value='200' WHERE key='current_balance'")
                conn.commit()
            with patch("database.os.name", "nt"), patch("database.os.getcwd", return_value=directory):
                db._migrate_legacy_windows_database()
            self.assertEqual(self._read_balance(target), "200")


if __name__ == "__main__":
    unittest.main()
