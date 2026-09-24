from __future__ import annotations

import asyncio
import inspect
import unittest

from config import Config
from runtime_v4 import (
    APP_VERSION,
    FIVE_CANDLE_PATTERNS,
    GREEN,
    RED,
    ClosedCandle,
    PatternSignalBot,
    next_bet_step,
    recognize_five_candle_pattern,
    result_for_direction,
)


class PatternV4Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "4.0.1")

    def test_exact_24_patterns_from_reference_image(self):
        expected = {
            "RGGRR": RED,
            "GRRGR": RED,
            "GGRRR": GREEN,
            "RRGGR": GREEN,
            "RGGRG": GREEN,
            "GRRGG": GREEN,
            "GGRRG": RED,
            "RRGGG": RED,
            "RGGGR": GREEN,
            "RRRGR": RED,
            "GGGRR": GREEN,
            "GRRRR": RED,
            "RGRRR": GREEN,
            "GRGGR": RED,
            "RRGRR": RED,
            "GGRGR": GREEN,
            "RGGGG": GREEN,
            "RRRGG": RED,
            "GGGRG": GREEN,
            "GRRRG": RED,
            "RGRRG": GREEN,
            "GRGGG": RED,
            "RRGRG": RED,
            "GGRGG": GREEN,
        }
        self.assertEqual(FIVE_CANDLE_PATTERNS, expected)
        for pattern, direction in expected.items():
            self.assertEqual(recognize_five_candle_pattern(pattern), direction)

    def test_unknown_or_doji_pattern_has_no_signal(self):
        self.assertIsNone(recognize_five_candle_pattern("GGGGG"))
        self.assertIsNone(recognize_five_candle_pattern([GREEN, RED, None, GREEN, RED]))

    def test_two_step_money_sequence(self):
        self.assertEqual(next_bet_step(1, "WIN"), 2)
        self.assertEqual(next_bet_step(1, "LOSS"), 1)
        self.assertEqual(next_bet_step(2, "WIN"), 1)
        self.assertEqual(next_bet_step(2, "LOSS"), 1)

    def test_direction_result(self):
        self.assertEqual(result_for_direction(GREEN, GREEN), "WIN")
        self.assertEqual(result_for_direction(RED, RED), "WIN")
        self.assertEqual(result_for_direction(GREEN, RED), "LOSS")
        self.assertEqual(result_for_direction(RED, GREEN), "LOSS")
        self.assertEqual(result_for_direction(RED, None), "VOID")

    def test_just_closed_live_m5_is_the_fifth_candle(self):
        # Reference row: 4 previous candles RGGR + the live candle that has
        # just closed RED => RGGRR => buy RED on the immediately following M5.
        def candle(index: int, color: str) -> ClosedCandle:
            open_time = index * 300_000
            if color == GREEN:
                open_price, close_price = 100.0, 101.0
            else:
                open_price, close_price = 101.0, 100.0
            return ClosedCandle(
                open_time=open_time,
                close_time=open_time + 299_999,
                open=open_price,
                close=close_price,
            )

        candles = [candle(i, color) for i, color in enumerate("RGGRR")]
        bot = PatternSignalBot(Config(telegram_token="x", telegram_chat_id="1"))
        window = bot._window_ending_at(candles[-1], candles)
        self.assertEqual([item.color for item in window], list("RGGRR"))
        self.assertEqual(recognize_five_candle_pattern(item.color for item in window), RED)
        self.assertEqual(window[-1].open_time, candles[-1].open_time)

    def test_result_message_is_sent_before_new_entry_path(self):
        source = inspect.getsource(PatternSignalBot._process_closed_candle)
        self.assertLess(source.index("_settle_for_candle"), source.index("_create_signal_from_window"))
        self.assertIn("result_message_ready", source)

    def test_telegram_messages_show_win_loss_totals(self):
        signal_source = inspect.getsource(PatternSignalBot.signal_text)
        result_source = inspect.getsource(PatternSignalBot.result_text)
        self.assertIn("Thắng:", signal_source)
        self.assertIn("Thua:", signal_source)
        self.assertIn("Thắng:", result_source)
        self.assertIn("Thua:", result_source)

        bot = PatternSignalBot(Config(telegram_token="x", telegram_chat_id="1"))
        text = asyncio.run(bot.result_text(
            {
                "direction": RED,
                "bet_step": 1,
                "bet_amount": 1.0,
                "target_open_time": 0,
                "target_close_time": 300_000,
            },
            RED,
            "WIN",
            0.8,
            {"wins": 7, "losses": 3, "voids": 0, "pnl": 2.4, "start_balance": 100.0, "end_balance": 102.4},
        ))
        self.assertIn("THẮNG", text)
        self.assertIn("Thắng: <b>7</b>", text)
        self.assertIn("Thua: <b>3</b>", text)


if __name__ == "__main__":
    unittest.main()
