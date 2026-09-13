import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_v3 import DEFAULT_CLOUD_DB, load_cloud_environment


CLOUD_KEYS = {
    "CLOUD_TELEGRAM_BOT_TOKEN",
    "CLOUD_TELEGRAM_CHAT_ID",
    "CLOUD_SYMBOL",
    "CLOUD_BASE_BET",
    "CLOUD_PAYOUT_RATE",
    "CLOUD_DECISION_SECOND",
    "CLOUD_MAX_BET",
    "CLOUD_TIMEZONE",
    "CLOUD_LOG_LEVEL",
    "CLOUD_DATABASE_PATH",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "SYMBOL",
    "BASE_BET",
    "PAYOUT_RATE",
    "DECISION_SECOND",
    "MAX_BET",
    "TIMEZONE",
    "LOG_LEVEL",
    "DATABASE_PATH",
}


class CloudV3Tests(unittest.TestCase):
    def clean_environment(self):
        env = os.environ.copy()
        for key in CLOUD_KEYS:
            env.pop(key, None)
        return env

    def test_cloud_requires_separate_telegram_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env.cloud"
            env_file.write_text("CLOUD_SYMBOL=BTCUSDT\n", encoding="utf-8")
            with patch.dict(os.environ, self.clean_environment(), clear=True):
                with self.assertRaisesRegex(ValueError, "CLOUD_TELEGRAM_BOT_TOKEN"):
                    load_cloud_environment(env_file)

    def test_cloud_promotes_only_cloud_credentials_and_uses_separate_db(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env.cloud"
            env_file.write_text(
                "CLOUD_TELEGRAM_BOT_TOKEN=cloud-token\n"
                "CLOUD_TELEGRAM_CHAT_ID=12345\n"
                "CLOUD_SYMBOL=ETHUSDT\n"
                "CLOUD_DECISION_SECOND=17\n",
                encoding="utf-8",
            )
            clean = self.clean_environment()
            clean["TELEGRAM_BOT_TOKEN"] = "windows-token-that-must-not-win"
            clean["TELEGRAM_CHAT_ID"] = "999"
            with patch.dict(os.environ, clean, clear=True):
                load_cloud_environment(env_file)
                self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], "cloud-token")
                self.assertEqual(os.environ["TELEGRAM_CHAT_ID"], "12345")
                self.assertEqual(os.environ["SYMBOL"], "ETHUSDT")
                self.assertEqual(os.environ["DECISION_SECOND"], "17")
                self.assertEqual(Path(os.environ["DATABASE_PATH"]), DEFAULT_CLOUD_DB)

    def test_cloud_custom_database_path_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            custom_db = Path(directory) / "persistent" / "cloud.db"
            env_file = Path(directory) / ".env.cloud"
            env_file.write_text(
                "CLOUD_TELEGRAM_BOT_TOKEN=cloud-token\n"
                "CLOUD_TELEGRAM_CHAT_ID=12345\n"
                f"CLOUD_DATABASE_PATH={custom_db}\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, self.clean_environment(), clear=True):
                load_cloud_environment(env_file)
                self.assertEqual(Path(os.environ["DATABASE_PATH"]), custom_db)


if __name__ == "__main__":
    unittest.main()
