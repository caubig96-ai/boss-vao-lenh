from __future__ import annotations

import unittest

import aiosqlite

from candle_color_model import ColorForecast
from runtime_v375 import (
    APP_VERSION,
    CompactTelegramBotV375,
    SIGNAL_MODE_INVERSE,
    SIGNAL_MODE_NORMAL,
    TradingSignalBotV3,
    invert_forecast,
)


async def _noop_handler(*_args, **_kwargs):
    return None


class DictDB:
    def __init__(self, conn, values=None):
        self.conn = conn
        self.values = dict(values or {})

    async def get(self, key, default=""):
        return self.values.get(key, default)

    async def set(self, key, value):
        self.values[key] = str(value)


class V375PureTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "3.7.5")

    def test_keyboard_has_inverse_toggle_and_no_old_mode_selector(self):
        telegram = CompactTelegramBotV375("token", "1", _noop_handler)
        callbacks = [
            button["callback_data"]
            for row in telegram.keyboard(True)["inline_keyboard"]
            for button in row
        ]
        self.assertIn("toggle_inverse_signal", callbacks)
        self.assertNotIn("analysis_mode", callbacks)

    def test_inverse_recomputes_real_opposite_agreement(self):
        forecast = ColorForecast(
            direction="UP",
            green_probability=0.70,
            confidence=0.70,
            agreement=4,
            components={
                "knn": 0.70,
                "sequence": 0.60,
                "body": 0.62,
                "close_position": 0.58,
                "wick": 0.42,
                "regime": 0.40,
            },
            sequence_samples=50,
            sequence_by_length={2: 20},
            knn_samples=80,
            knn_mean_distance=0.2,
        )
        inverse = invert_forecast(forecast)
        self.assertEqual(inverse.direction, "DOWN")
        self.assertEqual(inverse.agreement, 2)
        self.assertAlmostEqual(inverse.confidence, 0.30)
        # Underlying six analyses stay untouched rather than being fake-flipped.
        self.assertEqual(inverse.components, forecast.components)


class V375AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_agreement_stats_are_separate_for_normal_and_inverse(self):
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row
        try:
            await conn.execute(
                "CREATE TABLE color_predictions("
                "market_open_time INTEGER, agreement INTEGER, status TEXT, result TEXT, signal_mode TEXT)"
            )
            await conn.executemany(
                "INSERT INTO color_predictions VALUES(?,?,?,?,?)",
                [
                    (1, 4, "SETTLED", "WIN", SIGNAL_MODE_NORMAL),
                    (2, 4, "SETTLED", "LOSS", SIGNAL_MODE_INVERSE),
                    (3, 4, "SETTLED", "LOSS", SIGNAL_MODE_INVERSE),
                ],
            )
            await conn.commit()

            bot = TradingSignalBotV3.__new__(TradingSignalBotV3)
            bot.db = DictDB(conn, {"stats_reset_at": "0", "inverse_signal_enabled": "0"})
            normal = await bot.agreement_stats_since_reset()
            self.assertEqual(normal[4]["wins"], 1)
            self.assertEqual(normal[4]["losses"], 0)

            bot.db.values["inverse_signal_enabled"] = "1"
            inverse = await bot.agreement_stats_since_reset()
            self.assertEqual(inverse[4]["wins"], 0)
            self.assertEqual(inverse[4]["losses"], 2)
        finally:
            await conn.close()

    async def test_toggle_callback_persists_mode(self):
        conn = await aiosqlite.connect(":memory:")
        try:
            bot = TradingSignalBotV3.__new__(TradingSignalBotV3)
            bot.db = DictDB(conn, {"inverse_signal_enabled": "0", "manual_enabled": "1"})

            class FakeTelegram:
                inverse_enabled = False
                async def send(self, *_args, **_kwargs):
                    return 1

            bot.telegram = FakeTelegram()
            await TradingSignalBotV3.handle_telegram(bot, "callback", "toggle_inverse_signal", {})
            self.assertEqual(bot.db.values["inverse_signal_enabled"], "1")
            self.assertTrue(bot.telegram.inverse_enabled)
        finally:
            await conn.close()


if __name__ == "__main__":
    unittest.main()
