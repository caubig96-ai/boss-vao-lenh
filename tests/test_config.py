import os
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError

from config import Config


class ConfigTests(unittest.TestCase):
    def test_vietnam_timezone_fallback(self):
        with patch("config.ZoneInfo", side_effect=ZoneInfoNotFoundError):
            tz = Config(timezone_name="Asia/Ho_Chi_Minh").timezone
        offset = datetime(2026, 1, 1, tzinfo=tz).utcoffset()
        self.assertEqual(offset.total_seconds(), 7 * 60 * 60)

    def test_default_decision_second_is_10(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DECISION_SECOND", None)
            config = Config()
        self.assertEqual(config.decision_second, 10)


if __name__ == "__main__":
    unittest.main()
