import asyncio
import unittest
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database import Database
from models import Candle, Prediction
from pair_pattern_model import (
    METHODS,
    PairMatch,
    candle_direction,
    find_pair_matches,
    pair_shape_similarity,
    select_method,
    summarize,
)
from runtime_v379 import TradingSignalBotV3, TwoMethodTelegram


def candle(index, open_price, high, low, close):
    start = index * 300_000
    return Candle("5m", start, start + 299_999, open_price, high, low, close, 1, True)


class PairModelTests(unittest.TestCase):
    def test_binary_color(self):
        self.assertEqual(candle_direction(candle(0, 100, 101, 99, 100)), "UP")
        self.assertEqual(candle_direction(candle(0, 100, 101, 98, 99)), "DOWN")

    def test_color_and_shape_use_known_historical_successor(self):
        history = [
            candle(0, 100, 104, 99, 103),       # green candidate
            candle(1, 103, 104, 99, 100),       # red candidate
            candle(2, 100, 101, 95, 96),        # known next: red
            candle(3, 96, 98, 94, 95),
            candle(4, 95, 97, 93, 94),
            candle(5, 200, 208, 198, 206),      # same normalized shape as index 0
            candle(6, 206, 208, 198, 200),      # same normalized shape as index 1
        ]
        matches = find_pair_matches(history)
        self.assertEqual(matches["color_pair"].raw_direction, "DOWN")
        self.assertEqual(matches["color_pair"].matched_next_open_time, history[2].open_time)
        self.assertEqual(matches["shape_pair"].raw_direction, "DOWN")
        self.assertGreaterEqual(matches["shape_pair"].similarity, .99)

    def test_shape_threshold_rejects_unrelated_pair(self):
        history = [
            candle(0, 100, 110, 90, 100),
            candle(1, 100, 110, 90, 100),
            candle(2, 100, 101, 99, 100),
            candle(3, 100, 101, 99, 100),
            candle(4, 100, 101, 99, 100),
            candle(5, 100, 101, 99, 101),
            candle(6, 101, 102, 100, 102),
        ]
        self.assertIsNone(find_pair_matches(history)["shape_pair"])

    def test_selects_stronger_raw_history_and_inverts_loser(self):
        matches = {
            "color_pair": PairMatch("color_pair", "UP", 1.0, 0, 600_000),
            "shape_pair": PairMatch("shape_pair", "UP", .94, 300_000, 900_000),
        }
        stats = {
            "color_pair": summarize(["WIN"] * 7 + ["LOSS"] * 3),
            "shape_pair": summarize(["LOSS"] * 8 + ["WIN"] * 2),
        }
        selected = select_method(matches, stats)
        self.assertEqual(selected["method"], "shape_pair")
        self.assertTrue(selected["inverse"])
        self.assertEqual(selected["direction"], "DOWN")
        self.assertEqual(stats["shape_pair"]["losses"], 8)

    def test_no_history_keeps_raw_and_uses_match_quality_tiebreak(self):
        matches = {
            "color_pair": PairMatch("color_pair", "DOWN", 1.0, 0, 600_000),
            "shape_pair": PairMatch("shape_pair", "UP", .95, 300_000, 900_000),
        }
        stats = {method: summarize([]) for method in METHODS}
        selected = select_method(matches, stats)
        self.assertEqual(selected["method"], "color_pair")
        self.assertEqual(selected["direction"], "DOWN")


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(":memory:")
        await self.db.open()
        bot = self.bot = TradingSignalBotV3.__new__(TradingSignalBotV3)
        bot.db = self.db
        bot.config = SimpleNamespace(base_bet=1, max_bet=100, payout_rate=.9, timezone=timezone.utc)
        bot._decision_send_lock = asyncio.Lock()
        bot.decision_tasks = {}
        bot.live_price = 101
        bot.live_m5 = Candle("5m", 3_000_000, 3_299_999, 100, 101, 99, 100, 1, False)
        bot._closed_m5_history = AsyncMock(return_value=[])
        bot.signals_enabled = AsyncMock(return_value=True)
        bot.telegram = SimpleNamespace(send=AsyncMock(return_value=11), detail_open_time=None, last_error="")
        bot.apply_money_management = AsyncMock()
        bot.http = None
        await bot._ensure_pair_schema()

    async def asyncTearDown(self):
        await self.db.close()

    async def test_decision_records_two_methods_and_inverse_result_stays_raw(self):
        await self.db.conn.executemany(
            "INSERT INTO pair_predictions VALUES(?,?,?,?,?,?,?,?)",
            [(i * 300_000, i * 300_000 + 299_999, "shape_pair", "UP", .95, 0, 600_000, "LOSS")
             for i in range(10)],
        )
        await self.db.conn.commit()
        matches = {
            "color_pair": PairMatch("color_pair", "UP", 1.0, 0, 600_000),
            "shape_pair": PairMatch("shape_pair", "UP", .96, 300_000, 900_000),
        }
        with patch("runtime_v379.find_pair_matches", return_value=matches):
            await self.bot.make_decision(3_000_000, 0)
        row = await self.bot._row_for_signal(3_000_000)
        self.assertEqual(row["direction"], "DOWN")
        self.assertEqual(self.bot.telegram.send.await_count, 2)
        self.assertIn("MUA GIẢM NGAY", self.bot.telegram.send.call_args.args[0])
        count = await (await self.db.conn.execute(
            "SELECT COUNT(*) count FROM pair_predictions WHERE market_open_time=3000000"
        )).fetchone()
        self.assertEqual(count["count"], 2)

        await self.bot.settle_market(Candle("5m", 3_000_000, 3_299_999, 100, 101, 98, 99, 1, True))
        row = await self.bot._row_for_signal(3_000_000)
        self.assertEqual(row["result"], "WIN")
        raw = await (await self.db.conn.execute(
            "SELECT result FROM pair_predictions WHERE market_open_time=3000000 AND method='shape_pair'"
        )).fetchone()
        self.assertEqual(raw["result"], "LOSS")

    async def test_equal_open_close_settles_real_signal_as_binary(self):
        await self.db.create_signal(Prediction(
            3_000_000, 3_299_999, 100, 100, "UP", .5, .5, .5, 0, 1, 1, False,
        ))
        row = (await self.db.pending())[0]
        await self.bot.settle_row(row, 100)
        settled = await self.bot._row_for_signal(3_000_000)
        self.assertEqual(settled["result"], "WIN")
        self.assertNotEqual(settled["result"], "TIE")

    async def test_actual_wins_button_and_report(self):
        keyboard = TwoMethodTelegram("token", "1", AsyncMock()).keyboard()
        callbacks = [button["callback_data"] for row in keyboard["inline_keyboard"] for button in row]
        self.assertIn("actual_wins", callbacks)
        self.assertIn("pair_stats", callbacks)
        self.assertNotIn("analysis_mode", callbacks)
        self.assertNotIn("toggle_inverse_signal", callbacks)
        self.assertIn("Chưa có phiên thắng", await self.bot.actual_wins_text())

    def test_platform_entrypoints_match(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("cloud_v3.py", "desktop_v379.pyw"):
            self.assertIn(
                "from runtime_v379 import APP_VERSION, TradingSignalBotV3",
                (root / name).read_text(encoding="utf-8"),
            )
        self.assertIn("desktop_v379.pyw", (root / "build_windows.bat").read_text())
