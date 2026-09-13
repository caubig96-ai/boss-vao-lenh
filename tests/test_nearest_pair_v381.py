import unittest

from models import Candle
from pair_pattern_model import find_nearest_pair_matches, find_pair_matches
from runtime_v381 import APP_VERSION, MATCHING_RULE, TradingSignalBotV3


def candle(index, open_price, high, low, close):
    start = index * 300_000
    return Candle("5m", start, start + 299_999, open_price, high, low, close, 1, True)


def pattern_history(outcomes):
    history = []
    for outcome in outcomes:
        i = len(history)
        history += [
            candle(i, 110, 110, 95, 100),
            candle(i + 1, 100, 120, 100, 120),
            candle(i + 2, 100, 105, 95, 101 if outcome == "UP" else 99),
        ]
    i = len(history)
    return history + [
        candle(i, 1000, 1000, 998.9, 999),
        candle(i + 1, 999, 999.1, 999, 999.1),
    ]


class NearestPairV381Tests(unittest.TestCase):
    def test_nearest_pair_beats_older_majority(self):
        history = pattern_history(["UP", "UP", "DOWN"])

        legacy = find_pair_matches(history)["color_pair"]
        nearest = find_nearest_pair_matches(history)["color_pair"]

        self.assertEqual(legacy.raw_direction, "UP")
        self.assertEqual(nearest.raw_direction, "DOWN")
        self.assertEqual(nearest.matched_open_time, 6 * 300_000)
        self.assertEqual(nearest.matched_next_open_time, 8 * 300_000)

    def test_nearest_pair_uses_single_successor_not_vote_counts(self):
        nearest = find_nearest_pair_matches(pattern_history(["DOWN", "UP", "UP"]))["color_pair"]

        self.assertEqual(nearest.raw_direction, "UP")
        self.assertEqual(nearest.green_count, 1)
        self.assertEqual(nearest.red_count, 0)

    def test_runtime_selects_requested_nearest_direction(self):
        matches = find_nearest_pair_matches(pattern_history(["UP", "UP", "DOWN"]))
        stats = {
            "color_pair": {"wins": 5, "losses": 5, "decided": 10, "win_rate": 0.5, "loss_rate": 0.5},
            "shape_pair": {"wins": 6, "losses": 4, "decided": 10, "win_rate": 0.6, "loss_rate": 0.4},
        }

        selected = TradingSignalBotV3.select_requested_method(matches, stats, "color_pair")

        self.assertEqual(selected["direction"], "DOWN")
        self.assertEqual(selected["match"]["red_count"], 1)

    def test_version_and_matching_rule_are_new(self):
        self.assertEqual(APP_VERSION, "3.8.1")
        self.assertEqual(MATCHING_RULE, "nearest_pair_v4")


if __name__ == "__main__":
    unittest.main()
