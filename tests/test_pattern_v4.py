from __future__ import annotations

import unittest

from runtime_v4 import (
    APP_VERSION,
    FIVE_CANDLE_PATTERNS,
    GREEN,
    RED,
    next_bet_step,
    recognize_five_candle_pattern,
    result_for_direction,
)


class PatternV4Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "4.0.0")

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


if __name__ == "__main__":
    unittest.main()
