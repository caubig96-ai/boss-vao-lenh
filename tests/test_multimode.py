import asyncio
import os
import tempfile
import unittest

from database import Database
from indicators import ANALYSIS_MODES, all_mode_predictions, blended_prediction
from models import Candle
from telegram_v3 import TelegramBotV3


def candles(interval: str, count: int, rising: bool = True):
    width = 60_000 if interval == "1m" else 300_000
    price = 100.0
    step = 0.25 if rising else -0.25
    result = []
    for i in range(count):
        close = price + step
        result.append(Candle(
            interval,
            i * width,
            (i + 1) * width - 1,
            price,
            max(price, close) + 0.08,
            min(price, close) - 0.08,
            close,
            100.0 + i,
            True,
        ))
        price = close
    return result


class MultiModeIndicatorTests(unittest.TestCase):
    def test_all_nine_modes_are_available(self):
        self.assertEqual(len(ANALYSIS_MODES), 9)
        self.assertEqual(
            set(ANALYSIS_MODES),
            {"AUTO", "M1", "M5", "AGREE", "MOMENTUM", "STRUCTURE", "WICK", "PATTERN", "BREAKOUT"},
        )

    def test_every_mode_returns_mandatory_direction(self):
        results = all_mode_predictions(
            candles("1m", 200, True),
            candles("5m", 200, True),
            150.0,
            149.0,
        )
        self.assertEqual(set(results), set(ANALYSIS_MODES))
        for result in results.values():
            self.assertIn(result[0], ("UP", "DOWN"))
            self.assertGreaterEqual(result[1], 0.5)
            self.assertLessEqual(result[1], 0.95)

    def test_selected_mode_matches_parallel_result(self):
        m1 = candles("1m", 200, True)
        m5 = candles("5m", 200, False)
        all_results = all_mode_predictions(m1, m5, 100.0, 100.0)
        for mode in ANALYSIS_MODES:
            self.assertEqual(
                blended_prediction(m1, m5, 100.0, 100.0, mode=mode),
                all_results[mode],
            )


class ModeStatsDatabaseTests(unittest.TestCase):
    def test_shadow_modes_are_scored_independently(self):
        async def scenario(path: str):
            db = Database(path)
            await db.open()
            predictions = {
                "AUTO": ("UP", 0.66, 0.60, 0.60, 20),
                "M1": ("DOWN", 0.61, 0.40, 0.40, 20),
            }
            await db.create_mode_signals(1_000, 301_000, 100.0, predictions)
            self.assertEqual(len(await db.pending_modes()), 2)
            await db.settle_mode_signals(1_000, 101.0)
            stats = await db.mode_stats(0)
            self.assertEqual(stats["AUTO"]["wins"], 1)
            self.assertEqual(stats["AUTO"]["losses"], 0)
            self.assertEqual(stats["M1"]["wins"], 0)
            self.assertEqual(stats["M1"]["losses"], 1)
            self.assertEqual(stats["AUTO"]["win_rate"], 100.0)
            self.assertEqual(stats["M1"]["win_rate"], 0.0)
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


class ModeMenuTests(unittest.TestCase):
    def test_mode_button_shows_selection_and_win_loss(self):
        text = TelegramBotV3._mode_button_text(
            "CÂN BẰNG",
            True,
            {"wins": 7, "losses": 3, "decided": 10, "win_rate": 70.0},
        )
        self.assertIn("✅", text)
        self.assertIn("7T/3B", text)
        self.assertIn("70.0%", text)

    def test_mode_button_without_history_is_explicit(self):
        text = TelegramBotV3._mode_button_text("BỨT PHÁ", False, None)
        self.assertIn("0T/0B", text)
        self.assertIn("--", text)


if __name__ == "__main__":
    unittest.main()
