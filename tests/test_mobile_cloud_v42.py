from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from config import Config
from mobile_web import MobileWebServer
from runtime_v4 import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class MobileCloudV42Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "4.2.1")

    def test_mobile_password_can_be_configured_independently(self):
        cfg = Config(
            telegram_token="x",
            telegram_chat_id="1",
            app_password="123",
            mobile_password="9876",
        )
        self.assertEqual(cfg.mobile_password, "9876")

    def test_mobile_server_requires_password_argument(self):
        params = inspect.signature(MobileWebServer.__init__).parameters
        self.assertIn("password", params)

    def test_phone_can_test_telegram_and_change_settings(self):
        source = (ROOT / "mobile_web.py").read_text(encoding="utf-8")
        self.assertIn("/api/test-telegram", source)
        self.assertIn("/api/settings", source)
        self.assertIn("boss_session", source)

    def test_systemd_is_always_on(self):
        source = (ROOT / "deploy" / "oracle" / "install.sh").read_text(encoding="utf-8")
        self.assertIn("Restart=always", source)
        self.assertIn("WantedBy=multi-user.target", source)
        self.assertIn("systemctl enable", source)

    def test_public_mobile_helper_checks_local_dashboard(self):
        source = (ROOT / "deploy" / "oracle" / "mobile_public.sh").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1", source)
        self.assertIn("api.ipify.org", source)
        self.assertIn("Destination Port", source)


if __name__ == "__main__":
    unittest.main()
