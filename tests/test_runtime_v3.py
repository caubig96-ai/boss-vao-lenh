import asyncio
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from config import Config
from runtime_v3 import TradingSignalBotV3, migrate_legacy_database, resolve_database_path


class RuntimeV3Tests(unittest.TestCase):
    def make_bot(self):
        with patch("runtime_v3.resolve_database_path", return_value=Path("test-v3.db")), \
             patch("runtime_v3.migrate_legacy_database", return_value=None):
            return TradingSignalBotV3(Config(telegram_token="test", telegram_chat_id="1"))

    def test_live_candle_changes_on_each_trade(self):
        bot = self.make_bot()
        self.assertTrue(bot._apply_trade_to_live("1m", 60_001, 100.0))
        self.assertFalse(bot._apply_trade_to_live("1m", 60_100, 105.0))
        self.assertFalse(bot._apply_trade_to_live("1m", 60_200, 98.0))
        self.assertEqual(bot.live_m1.open, 100.0)
        self.assertEqual(bot.live_m1.high, 105.0)
        self.assertEqual(bot.live_m1.low, 98.0)
        self.assertEqual(bot.live_m1.close, 98.0)

    def test_aggtrade_schedules_m5_without_waiting_for_kline(self):
        bot = self.make_bot()
        scheduled = []
        bot.schedule_decision = lambda candle, event_ms: scheduled.append((candle.open_time, event_ms))

        async def scenario():
            await bot.handle_market_message({"e": "aggTrade", "E": 300_010, "T": 300_010, "p": "100"})

        asyncio.run(scenario())
        self.assertEqual(bot.trade_ticks, 1)
        self.assertEqual(bot.live_m5.open_time, 300_000)
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0][0], 300_000)

    def test_decision_delay_allows_watchdog_recovery(self):
        self.assertAlmostEqual(TradingSignalBotV3.decision_delay(0, 10_000, 18), 8.0)
        self.assertEqual(TradingSignalBotV3.decision_delay(0, 19_000, 18), 0.0)
        self.assertIsNone(TradingSignalBotV3.decision_delay(0, 30_000, 18))

    def test_result_message_says_win_up_or_win_down(self):
        bot = self.make_bot()

        async def scenario():
            up = await bot.result_text({"direction": "UP"}, 101.0, "WIN", 0.8)
            down = await bot.result_text({"direction": "DOWN"}, 99.0, "WIN", 0.8)
            loss_down = await bot.result_text({"direction": "DOWN"}, 101.0, "LOSS", -1.0)
            return up, down, loss_down

        up, down, loss_down = asyncio.run(scenario())
        self.assertIn("ĐÃ THẮNG TĂNG", up)
        self.assertIn("ĐÃ THẮNG GIẢM", down)
        self.assertIn("ĐÃ THUA GIẢM", loss_down)

    def test_confidence_bucket_line_shows_rate_and_counts(self):
        text = TradingSignalBotV3._bucket_line(
            "🟢", "CAO ≥65.0%", {"wins": 7, "losses": 3, "ties": 1, "decided": 10, "win_rate": 70.0}
        )
        self.assertIn("70.0%", text)
        self.assertIn("7 thắng/3 thua", text)
        self.assertIn("1 hòa", text)

    @unittest.skipUnless(os.name == "nt", "Windows persistence semantics")
    def test_windows_relative_database_path_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}, clear=False):
            cfg = Config(telegram_token="x", telegram_chat_id="1", database_path="data/bot.db")
            expected = Path(directory) / "BossVaoLenh" / "data" / "bot.db"
            self.assertEqual(resolve_database_path(cfg), expected)

    @unittest.skipUnless(os.name == "nt", "Windows migration semantics")
    def test_empty_v2_target_is_recovered_from_richer_legacy_db(self):
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                legacy = Path(directory) / "data" / "bot.db"
                legacy.parent.mkdir(parents=True)
                with closing(sqlite3.connect(legacy)) as conn:
                    conn.execute("CREATE TABLE signals (market_open_time INTEGER PRIMARY KEY)")
                    conn.execute("INSERT INTO signals VALUES (123)")
                    conn.commit()

                target = Path(directory) / "persistent" / "bot.db"
                target.parent.mkdir(parents=True)
                with closing(sqlite3.connect(target)) as conn:
                    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
                    conn.commit()

                source = migrate_legacy_database(target, "data/bot.db")
                self.assertEqual(source.resolve(), legacy.resolve())
                with closing(sqlite3.connect(target)) as conn:
                    count = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
                self.assertEqual(count, 1)
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
