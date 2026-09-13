from __future__ import annotations

import asyncio
import inspect
import unittest

from runtime_v371 import APP_VERSION, TradingSignalBotV3


class SingleColorModeV371Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "3.7.1")

    def test_decision_path_does_not_generate_legacy_mode_signals(self):
        source = inspect.getsource(TradingSignalBotV3.make_decision)
        self.assertNotIn("all_mode_predictions", source)
        self.assertNotIn("create_mode_signals", source)
        self.assertIn("predict_next_color", source)
        self.assertIn("_save_color_prediction", source)

    def test_color_engine_is_always_the_only_enabled_mode(self):
        bot = object.__new__(TradingSignalBotV3)
        self.assertTrue(asyncio.run(bot.auto_mode_enabled()))
        self.assertEqual(asyncio.run(bot.current_analysis_mode()), "AUTO")

    def test_detail_and_menu_do_not_offer_legacy_mode_selection(self):
        menu_source = inspect.getsource(TradingSignalBotV3._send_auto_mode_menu)
        self.assertIn("COLOR ENGINE - CHẾ ĐỘ DUY NHẤT", menu_source)
        self.assertNotIn("M1 NHANH", menu_source)
        self.assertNotIn("M5 CHẮC", menu_source)
        self.assertNotIn("ĐỘNG LƯỢNG", menu_source)
        self.assertNotIn("MẪU 24H", menu_source)


if __name__ == "__main__":
    unittest.main()
