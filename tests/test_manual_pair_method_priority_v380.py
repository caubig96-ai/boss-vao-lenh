import unittest

from pair_pattern_model import PairMatch
from runtime_v380 import TradingSignalBotV3


class ManualPairMethodPriorityV380Tests(unittest.TestCase):
    @staticmethod
    def _match(method, direction, green, red):
        return PairMatch(
            method=method,
            raw_direction=direction,
            similarity=1.0,
            matched_open_time=1000,
            matched_next_open_time=1300,
            green_count=green,
            red_count=red,
        )

    def test_selected_shape_method_controls_signal(self):
        matches = {
            "color_pair": self._match("color_pair", "UP", 8, 3),
            "shape_pair": self._match("shape_pair", "DOWN", 4, 7),
        }
        stats = {
            "color_pair": {"wins": 7, "losses": 3, "decided": 10, "win_rate": 0.7, "loss_rate": 0.3},
            "shape_pair": {"wins": 6, "losses": 4, "decided": 10, "win_rate": 0.6, "loss_rate": 0.4},
        }

        selected = TradingSignalBotV3.select_requested_method(matches, stats, "shape_pair")

        self.assertEqual(selected["method"], "shape_pair")
        self.assertEqual(selected["direction"], "DOWN")
        self.assertEqual(selected["match"]["green_count"], 4)
        self.assertEqual(selected["match"]["red_count"], 7)

    def test_selected_color_method_does_not_fall_back_to_shape(self):
        matches = {
            "color_pair": None,
            "shape_pair": self._match("shape_pair", "UP", 8, 2),
        }
        stats = {
            "color_pair": {"wins": 5, "losses": 5, "decided": 10, "win_rate": 0.5, "loss_rate": 0.5},
            "shape_pair": {"wins": 8, "losses": 2, "decided": 10, "win_rate": 0.8, "loss_rate": 0.2},
        }

        selected = TradingSignalBotV3.select_requested_method(matches, stats, "color_pair")

        self.assertIsNone(selected)

    def test_loss_then_high_next_win_rate_marks_priority_in_50_60_band(self):
        raw_stats = {
            "wins": 55,
            "losses": 45,
            "decided": 100,
            "win_rate": 0.55,
            "loss_rate": 0.45,
        }
        results = ["LOSS", "WIN", "WIN", "LOSS", "WIN", "LOSS"]

        context = TradingSignalBotV3.priority_from_results(raw_stats, results)

        self.assertEqual(context["previous_result"], "LOSS")
        self.assertEqual(context["after_wins"], 2)
        self.assertEqual(context["after_losses"], 0)
        self.assertAlmostEqual(context["next_win_rate"], 1.0)
        self.assertTrue(context["in_50_60_band"])
        self.assertTrue(context["priority"])

    def test_loss_dominant_50_60_percent_also_uses_previous_result(self):
        raw_stats = {
            "wins": 44,
            "losses": 56,
            "decided": 100,
            "win_rate": 0.44,
            "loss_rate": 0.56,
        }
        results = ["LOSS", "WIN", "LOSS", "WIN", "LOSS"]

        context = TradingSignalBotV3.priority_from_results(raw_stats, results)

        self.assertEqual(context["previous_result"], "LOSS")
        self.assertTrue(context["in_50_60_band"])
        self.assertTrue(context["priority"])

    def test_priority_rule_is_not_used_outside_50_60_band(self):
        raw_stats = {
            "wins": 70,
            "losses": 30,
            "decided": 100,
            "win_rate": 0.70,
            "loss_rate": 0.30,
        }
        results = ["LOSS", "WIN", "LOSS", "WIN", "LOSS"]

        context = TradingSignalBotV3.priority_from_results(raw_stats, results)

        self.assertEqual(context["previous_result"], "LOSS")
        self.assertAlmostEqual(context["next_win_rate"], 1.0)
        self.assertFalse(context["in_50_60_band"])
        self.assertFalse(context["priority"])


if __name__ == "__main__":
    unittest.main()
