import asyncio
import os
import tempfile
import unittest

from database import Database
from models import Prediction
from runtime_v34 import TradingSignalBotV3


class CandleColorScoringTests(unittest.TestCase):
    def test_up_wins_only_on_green_candle(self):
        self.assertEqual(TradingSignalBotV3.candle_result("UP", 100.0, 101.0), "WIN")
        self.assertEqual(TradingSignalBotV3.candle_result("UP", 100.0, 99.0), "LOSS")

    def test_down_wins_only_on_red_candle(self):
        self.assertEqual(TradingSignalBotV3.candle_result("DOWN", 100.0, 99.0), "WIN")
        self.assertEqual(TradingSignalBotV3.candle_result("DOWN", 100.0, 101.0), "LOSS")

    def test_doji_is_tie(self):
        self.assertEqual(TradingSignalBotV3.candle_result("UP", 100.0, 100.0), "TIE")
        self.assertEqual(TradingSignalBotV3.candle_result("DOWN", 100.0, 100.0), "TIE")

    def test_shadow_scoring_ignores_wrong_target_and_uses_candle_color(self):
        async def scenario(path: str):
            db = Database(path)
            await db.open()
            try:
                open_time = 300_000
                # Deliberately absurd/wrong target. V3.4 must ignore it for result.
                await db.create_mode_signals(
                    open_time,
                    599_999,
                    999.0,
                    {"AUTO": ("DOWN", 0.70, 0.40, 0.40, 20)},
                )
                bot = object.__new__(TradingSignalBotV3)
                bot.db = db
                await bot._settle_modes_by_candle(open_time, 100.0, 99.0)
                stats = await db.mode_stats(0)
                self.assertEqual(stats["AUTO"]["wins"], 1)
                self.assertEqual(stats["AUTO"]["losses"], 0)
            finally:
                await db.close()

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            asyncio.run(scenario(path))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


class ConsecutivePairStatsTests(unittest.TestCase):
    def test_non_overlapping_pairs_are_1_2_then_3_4(self):
        async def scenario(path: str):
            db = Database(path)
            await db.open()
            try:
                await db.set_default("stats_reset_at", "0")
                results = ["WIN", "WIN", "LOSS", "LOSS", "WIN", "LOSS"]
                for index, result in enumerate(results, start=1):
                    open_time = index * 300_000
                    prediction = Prediction(
                        open_time,
                        open_time + 299_999,
                        100.0,
                        100.0,
                        "UP",
                        0.60,
                        0.50,
                        0.50,
                        10,
                        1.0,
                        1,
                        True,
                    )
                    self.assertTrue(await db.create_signal(prediction))
                    await db.settle(open_time, result, 101.0, 0.0)

                bot = object.__new__(TradingSignalBotV3)
                bot.db = db
                stats = await bot.pair_stats_since_reset()
                self.assertEqual(stats["complete_pairs"], 3)
                self.assertEqual(stats["win_pairs"], 1)   # orders 1+2
                self.assertEqual(stats["loss_pairs"], 1)  # orders 3+4
                self.assertEqual(stats["other_pairs"], 1) # orders 5+6
                self.assertEqual(stats["unpaired"], 0)
            finally:
                await db.close()

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            asyncio.run(scenario(path))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
