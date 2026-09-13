import asyncio
import os
import tempfile
import unittest

from database import Database
from runtime_v36 import (
    APP_VERSION,
    TradingSignalBotV3,
    consensus_is_recommended,
    next_from_sequence,
    select_best_worst,
)


class AutoConsensusPureTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "3.6.0")

    def test_sequence_rules_match_requested_green_red_patterns(self):
        self.assertEqual(next_from_sequence(["UP", "UP"])[0], "UP")
        self.assertEqual(next_from_sequence(["DOWN", "DOWN"])[0], "DOWN")
        self.assertEqual(next_from_sequence(["UP", "DOWN"])[0], "UP")
        self.assertEqual(next_from_sequence(["DOWN", "UP"])[0], "DOWN")
        self.assertEqual(next_from_sequence(["UP", "DOWN", "UP", "DOWN"])[0], "UP")
        self.assertEqual(next_from_sequence(["DOWN", "UP", "DOWN", "UP"])[0], "DOWN")

    def test_best_mode_and_worst_contrarian_mode_are_selected_from_results(self):
        stats = {
            "AUTO": {"wins": 8, "losses": 4, "decided": 12, "win_rate": 66.7},
            "M1": {"wins": 7, "losses": 5, "decided": 12, "win_rate": 58.3},
            "WICK": {"wins": 3, "losses": 9, "decided": 12, "win_rate": 25.0},
        }
        best, worst = select_best_worst(stats)
        self.assertEqual(best, "AUTO")
        self.assertEqual(worst, "WICK")

    def test_recommend_only_when_best_pattern_and_inverse_worst_agree(self):
        best_stats = {"wins": 8, "losses": 4, "decided": 12, "win_rate": 66.7}
        self.assertTrue(consensus_is_recommended("UP", best_stats, "UP", "UP"))
        self.assertFalse(consensus_is_recommended("UP", best_stats, "DOWN", "UP"))
        self.assertFalse(consensus_is_recommended("UP", best_stats, "UP", "DOWN"))


class NoCooldownV36Tests(unittest.TestCase):
    def _with_db(self, scenario):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            asyncio.run(scenario(path))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def test_old_risk_pause_never_blocks_signals(self):
        async def scenario(path: str):
            db = Database(path)
            await db.open()
            try:
                await db.set("manual_enabled", "1")
                await db.set("risk_pause_until", "9999999999999")
                bot = object.__new__(TradingSignalBotV3)
                bot.db = db
                self.assertTrue(await bot.signals_enabled())
                self.assertEqual(await db.get("risk_pause_until", "x"), "0")
                await db.set("manual_enabled", "0")
                self.assertFalse(await bot.signals_enabled())
            finally:
                await db.close()

        self._with_db(scenario)

    def test_loss_money_management_does_not_create_30_minute_pause(self):
        async def scenario(path: str):
            db = Database(path)
            await db.open()
            try:
                await db.set("current_balance", "10")
                await db.set("risk_cycle_losses", "1")
                await db.set("risk_pause_until", "123456")
                bot = object.__new__(TradingSignalBotV3)
                bot.db = db
                row = {"bet_step": 1}
                await bot.apply_money_management(row, "LOSS", -1.0)
                self.assertEqual(await db.get("risk_pause_until", "x"), "0")
                self.assertEqual(await db.get("risk_cycle_losses", "x"), "0")
                self.assertEqual(await db.get("bet_step", "x"), "1")
                self.assertAlmostEqual(float(await db.get("current_balance", "0")), 9.0)
            finally:
                await db.close()

        self._with_db(scenario)


if __name__ == "__main__":
    unittest.main()
