from __future__ import annotations

import unittest

import aiosqlite

from runtime_v377 import APP_VERSION, TradingSignalBotV3


class FakeDB:
    def __init__(self, conn, values=None):
        self.conn = conn
        self.values = dict(values or {})

    async def get(self, key, default=""):
        return self.values.get(key, default)


class V377Tests(unittest.IsolatedAsyncioTestCase):
    async def test_version_and_one_of_six_stats(self):
        self.assertEqual(APP_VERSION, "3.7.7")
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
                    (1, 1, "SETTLED", "WIN", "NORMAL"),
                    (2, 1, "SETTLED", "LOSS", "NORMAL"),
                    (3, 2, "SETTLED", "WIN", "NORMAL"),
                    (4, 1, "SETTLED", "LOSS", "INVERSE"),
                ],
            )
            await conn.commit()
            bot = TradingSignalBotV3.__new__(TradingSignalBotV3)
            bot.db = FakeDB(conn, {"stats_reset_at": "0", "inverse_signal_enabled": "0"})
            normal = await bot.agreement_stats_since_reset()
            self.assertEqual(set(normal), {1, 2, 3, 4, 5, 6})
            self.assertEqual(normal[1]["wins"], 1)
            self.assertEqual(normal[1]["losses"], 1)
            self.assertAlmostEqual(normal[1]["win_rate"], 50.0)

            bot.db.values["inverse_signal_enabled"] = "1"
            inverse = await bot.agreement_stats_since_reset()
            self.assertEqual(inverse[1]["wins"], 0)
            self.assertEqual(inverse[1]["losses"], 1)
        finally:
            await conn.close()


if __name__ == "__main__":
    unittest.main()
