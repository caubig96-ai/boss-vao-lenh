from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NativeIOSV421Tests(unittest.TestCase):
    def test_server_accepts_bearer_auth_for_native_ios(self):
        source = (ROOT / "mobile_web.py").read_text(encoding="utf-8")
        self.assertIn('Authorization', source)
        self.assertIn('auth.lower().startswith("bearer ")', source)
        self.assertIn("hmac.compare_digest(supplied, self.password)", source)

    def test_native_swiftui_app_exists(self):
        ios = ROOT / "ios" / "BossVaoLenhIOS" / "BossVaoLenhIOS"
        self.assertTrue((ios / "BossVaoLenhApp.swift").is_file())
        self.assertTrue((ios / "Views" / "DashboardView.swift").is_file())
        self.assertTrue((ios / "Views" / "SettingsView.swift").is_file())
        self.assertTrue((ios / "Networking" / "BossAPI.swift").is_file())

    def test_native_app_uses_cloud_api_not_webview(self):
        source = (
            ROOT / "ios" / "BossVaoLenhIOS" / "BossVaoLenhIOS" /
            "Networking" / "BossAPI.swift"
        ).read_text(encoding="utf-8")
        self.assertIn("/api/status", source)
        self.assertIn("/api/settings", source)
        self.assertIn("/api/test-telegram", source)
        self.assertIn('forHTTPHeaderField: "Authorization"', source)
        self.assertNotIn("WKWebView", source)

    def test_password_uses_ios_keychain(self):
        source = (
            ROOT / "ios" / "BossVaoLenhIOS" / "BossVaoLenhIOS" /
            "Security" / "KeychainStore.swift"
        ).read_text(encoding="utf-8")
        self.assertIn("SecItemAdd", source)
        self.assertIn("SecItemCopyMatching", source)

    def test_cloud_keeps_running_without_ios_app(self):
        source = (
            ROOT / "deploy" / "oracle" / "install.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("Restart=always", source)
        self.assertIn("systemctl enable", source)


if __name__ == "__main__":
    unittest.main()
