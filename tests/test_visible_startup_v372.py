from __future__ import annotations

from pathlib import Path
import unittest

from runtime_v372 import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class VisibleStartupV372Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "3.7.2")

    def test_windows_build_uses_visible_entrypoint(self):
        build = (ROOT / "build_windows.bat").read_text(encoding="utf-8")
        self.assertIn("desktop_v372.pyw", build)
        self.assertIn("VERSION: 3.7.2", build)

    def test_desktop_forces_visible_prompt_and_surfaces_engine_error(self):
        source = (ROOT / "desktop_v372.pyw").read_text(encoding="utf-8")
        self.assertIn("self.root.after(350, self.request_password)", source)
        self.assertIn("Engine không chạy", source)
        self.assertIn("messagebox.showerror", source)


if __name__ == "__main__":
    unittest.main()
