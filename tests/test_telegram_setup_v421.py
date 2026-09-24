from __future__ import annotations

import inspect
import unittest

from config import Config
from runtime_v4 import PatternSignalBot, TelegramSignalSender


class TelegramSetupV421Tests(unittest.TestCase):
    def test_sender_reports_unconfigured_without_crashing_app(self):
        sender = TelegramSignalSender("", "")
        self.assertFalse(sender.is_configured)

    def test_runtime_can_persist_telegram_credentials(self):
        self.assertTrue(hasattr(PatternSignalBot, "update_telegram_credentials"))
        source = inspect.getsource(PatternSignalBot.update_telegram_credentials)
        self.assertIn("telegram_token", source)
        self.assertIn("telegram_chat_id", source)

    def test_setup_keeps_running_when_market_sync_fails(self):
        source = inspect.getsource(PatternSignalBot.setup)
        self.assertIn("Initial market sync failed", source)
        self.assertIn("continuing in retry mode", source)

    def test_config_no_longer_requires_telegram(self):
        Config(telegram_token="", telegram_chat_id="").validate()


if __name__ == "__main__":
    unittest.main()
