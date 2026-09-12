from __future__ import annotations

import unittest
from types import SimpleNamespace

import aiosqlite

from runtime_v374 import (
    AGREEMENT_FALLBACK_THRESHOLD,
    AGREEMENT_POLICY_MIN_SAMPLES,
    APP_VERSION,
    CompactTelegramBotV374,
    TradingSignalBotV3,
)


class FakeDB:
    def __init__(self, conn):
        self.conn = conn

    async def get(self, key, default=""):
        return default


class V374PureTests(unittest.TestCase):
    def test_version_and_policy_defaults(self):
        self.assertEqual(APP_VERSION, "3.7.4")
        self.assertEqual(AGREEMENT_FALLBACK_THRESHOLD, 3)
        self.assertEqual(AGREEMENT_POLICY_MIN_SAMPLES, 20)

    def test_keyboard_keeps_controls_without_mode_selector(self):
        async def noop(*_args, **_kwargs):
            return None

        telegram = CompactTelegramBotV374("token", "1", noop)
        callbacks = [
            button["callback_data"]
            for row in telegram.keyboard(True)["inline_keyboard"]
            for button in row
        ]
        self.assertIn("status", callbacks)
        self.assertIn("setbet_help", callbacks)
        self.assertIn("threshold_stats", callbacks)
        self.assertIn("reset_stats", callbacks)
        self.assertNotIn("analysis_mode", callbacks)


class V374AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_is_acknowledged_before_handler(self):
        order = []

        async def handler(kind, value, update):
            order.append(("handler", kind, value))

        telegram = CompactTelegramBotV374("token", "123", handler)

        async def answer(callback_id, text=""):
            order.append(("ack", callback_id, text))

        telegram.answer_callback = answer  # type: ignore[method-assign]
        await telegram._dispatch({
            "callback_query": {
                "id": "cb-1",
                "from": {"id": 123},
                "data": "status",
            }
        })
        self.assertEqual(order[0][0], "ack")
        self.assertEqual(order[1], ("handler", "callback", "status"))

    async def test_agreement_stats_report_exact_2_to_6(self):
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row
        try:
            await conn.execute(
                "CREATE TABLE color_predictions(market_open_time INTEGER, agreement INTEGER, status TEXT, result TEXT)"
            )
            rows = [
                (1, 2, "SETTLED", "WIN"),
                (2, 2, "SETTLED", "LOSS"),
                (3, 3, "SETTLED", "WIN"),
                (4, 4, "SETTLED", "LOSS"),
                (5, 5, "SETTLED", "WIN"),
                (6, 6, "SETTLED", "WIN"),
            ]
            await conn.executemany("INSERT INTO color_predictions VALUES(?,?,?,?)", rows)
            await conn.commit()
            bot = TradingSignalBotV3.__new__(TradingSignalBotV3)
            bot.db = FakeDB(conn)
            stats = await bot.agreement_stats_since_reset()
            self.assertEqual(stats[2]["wins"], 1)
            self.assertEqual(stats[2]["losses"], 1)
            self.assertEqual(stats[6]["wins"], 1)
            self.assertEqual(set(stats), {2, 3, 4, 5, 6})
        finally:
            await conn.close()

    async def test_policy_can_raise_buy_now_threshold_when_history_supports_it(self):
        conn = await aiosqlite.connect(":memory:")
        conn.row_factory = aiosqlite.Row
        try:
            await conn.execute(
                "CREATE TABLE color_predictions(market_open_time INTEGER, agreement INTEGER, status TEXT, result TEXT)"
            )
            rows = []
            stamp = 1
            # 3/6 has mediocre history.
            for _ in range(30):
                rows.append((stamp, 3, "SETTLED", "WIN")); stamp += 1
            for _ in range(20):
                rows.append((stamp, 3, "SETTLED", "LOSS")); stamp += 1
            # 6/6 has enough samples and much stronger history.
            for _ in range(20):
                rows.append((stamp, 6, "SETTLED", "WIN")); stamp += 1
            await conn.executemany("INSERT INTO color_predictions VALUES(?,?,?,?)", rows)
            await conn.commit()
            bot = TradingSignalBotV3.__new__(TradingSignalBotV3)
            bot.db = FakeDB(conn)
            threshold, stats, _exact = await bot.agreement_entry_policy()
            self.assertEqual(threshold, 6)
            self.assertEqual(stats["wins"], 20)
            self.assertEqual(stats["losses"], 0)
        finally:
            await conn.close()


if __name__ == "__main__":
    unittest.main()
