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
    select_method,
    summarize,
    wick_type,
)
from runtime_v379 import TradingSignalBotV3, TwoMethodTelegram


def candle(index, open_price, high, low, close):
    start = index * 300_000
    return Candle("5m", start, start + 299_999, open_price, high, low, close, 1, True)


def pattern_history(outcomes):
    history = []
    for outcome in outcomes:
        i = len(history)
        history += [candle(i, 110, 110, 95, 100), candle(i+1, 100, 120, 100, 120),
                    candle(i+2, 100, 105, 95, 101 if outcome == "UP" else 99)]
    i = len(history)
    # Radically different body/wick lengths, same discrete types and colors.
    return history + [candle(i, 1000, 1000, 998.9, 999), candle(i+1, 999, 999.1, 999, 999.1)]


class PairModelTests(unittest.TestCase):
    def test_four_wick_types(self):
        for h, l, expected in [(103,100,(True,False)), (102,99,(False,True)),
                               (103,99,(True,True)), (102,100,(False,False))]:
            self.assertEqual(wick_type(candle(0,100,h,l,102)), expected)

    def test_counts_all_matches_not_just_latest_and_ignores_lengths(self):
        match = find_pair_matches(pattern_history(["UP", "UP", "DOWN"]))["color_pair"]
        self.assertEqual((match.green_count, match.red_count, match.raw_direction), (2,1,"UP"))

    def test_red_majority(self):
        match = find_pair_matches(pattern_history(["DOWN", "DOWN", "UP"]))["color_pair"]
        self.assertEqual((match.green_count, match.red_count, match.raw_direction), (1,2,"DOWN"))

    def test_tie_has_counts_but_no_signal_or_shape_fallback(self):
        matches = find_pair_matches(pattern_history(["UP", "DOWN"]))
        self.assertIsNone(matches["color_pair"].raw_direction)
        matches["shape_pair"] = PairMatch("shape_pair", "UP", 1, 0, 0, 3, 1)
        self.assertIsNone(select_method(matches, {m:summarize([]) for m in METHODS}))

    def test_wrong_wick_or_color_or_order_is_rejected(self):
        for replacement in [candle(0,110,111,100,100), candle(0,100,110,95,110)]:
            h = pattern_history(["UP"])
            h[0] = replacement
            self.assertIsNone(find_pair_matches(h)["color_pair"])
        h = pattern_history(["UP"])
        h[0], h[1] = candle(0,100,120,100,120), candle(1,110,110,95,100)
        self.assertIsNone(find_pair_matches(h)["color_pair"])

    def test_missing_live_future_and_outside_24h_do_not_vote(self):
        h = pattern_history(["UP"])
        before = h[-1].open_time + 300_000
        live = candle(len(h),100,101,99,101)
        live.closed = False
        self.assertEqual(find_pair_matches(h+[live],before)["color_pair"].green_count, 1)
        self.assertIsNone(find_pair_matches(h, before+300_000)["color_pair"])
        h[0].open_time -= 86_400_000
        self.assertIsNone(find_pair_matches(h,before)["color_pair"])

    def test_nonconsecutive_historical_triplet_is_rejected(self):
        h = pattern_history(["UP"])
        h[0].open_time -= 300_000
        self.assertIsNone(find_pair_matches(h)["color_pair"])

    def test_loss_history_does_not_reverse_majority(self):
        matches = find_pair_matches(pattern_history(["UP", "UP", "DOWN"]))
        stats = {m:summarize(["LOSS"]*10) for m in METHODS}
        selected = select_method(matches, stats)
        self.assertFalse(selected["inverse"])
        self.assertEqual(selected["direction"], "UP")
        self.assertEqual(selected["effective_rate"], 2/3)

    def test_binary_color(self):
        self.assertEqual(candle_direction(candle(0,100,101,99,100)), "UP")


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

    async def test_old_rule_results_are_preserved_but_excluded_from_ranking(self):
        await self.db.conn.execute(
            "INSERT INTO pair_predictions VALUES(0,299999,'color_pair','UP',1,0,0,'WIN')")
        await self.db.conn.execute("INSERT INTO pair_decisions VALUES(0,'{}')")
        self.assertEqual((await self.bot.pair_stats(300000))['color_pair']['decided'], 0)
        await self.db.conn.execute(
            "UPDATE pair_decisions SET snapshot=?", ('{"matching_rule":"wick_votes_v3"}',))
        self.assertEqual((await self.bot.pair_stats(300000))['color_pair']['wins'], 1)

    async def test_decision_majority_direction_and_raw_result_agree(self):
        await self.db.conn.executemany(
            "INSERT INTO pair_predictions VALUES(?,?,?,?,?,?,?,?)",
            [(i * 300_000, i * 300_000 + 299_999, "shape_pair", "UP", .95, 0, 600_000, "LOSS")
             for i in range(10)],
        )
        await self.db.conn.executemany(
            "INSERT INTO pair_decisions VALUES(?,?)",
            [(i * 300_000, '{"matching_rule":"wick_votes_v3"}') for i in range(10)],
        )
        await self.db.conn.commit()
        matches = {
            "color_pair": PairMatch("color_pair", "UP", 1.0, 0, 600_000, 2, 1),
            "shape_pair": PairMatch("shape_pair", "DOWN", 1.0, 300_000, 900_000, 1, 4),
        }
        with patch("runtime_v379.find_pair_matches", return_value=matches):
            await self.bot.make_decision(3_000_000, 0)
        row = await self.bot._row_for_signal(3_000_000)
        self.assertEqual(row["direction"], "UP")
        self.assertEqual(self.bot.telegram.send.await_count, 2)
        self.assertIn("MUA TĂNG NGAY", self.bot.telegram.send.call_args.args[0])
        count = await (await self.db.conn.execute(
            "SELECT COUNT(*) count FROM pair_predictions WHERE market_open_time=3000000"
        )).fetchone()
        self.assertEqual(count["count"], 2)

        await self.bot.settle_market(Candle("5m", 3_000_000, 3_299_999, 100, 101, 98, 99, 1, True))
        row = await self.bot._row_for_signal(3_000_000)
        self.assertEqual(row["result"], "LOSS")
        raw = await (await self.db.conn.execute(
            "SELECT result FROM pair_predictions WHERE market_open_time=3000000 AND method='color_pair'"
        )).fetchone()
        self.assertEqual(raw["result"], "LOSS")

    async def test_tied_votes_send_no_buy_once_and_store_counts(self):
        h = pattern_history(["UP", "DOWN"])
        shift = 3_000_000 - (h[-1].open_time + 300_000)
        for c in h:
            c.open_time += shift
            c.close_time += shift
        self.bot._closed_m5_history.return_value = h
        await self.bot.make_decision(3_000_000, 0)
        await self.bot.make_decision(3_000_000, 0)
        self.assertIsNone(await self.bot._row_for_signal(3_000_000))
        self.assertEqual(self.bot.telegram.send.await_count, 1)
        snapshot = await self.bot._pair_decision(3_000_000)
        self.assertEqual(snapshot["matches"]["color_pair"]["green_count"], 1)
        self.assertEqual(snapshot["matches"]["color_pair"]["red_count"], 1)
        self.assertIsNone(snapshot["selected"])

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
