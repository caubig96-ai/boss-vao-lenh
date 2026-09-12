import unittest

from runtime_v361 import (
    ADAPTIVE_INVERT_MIN_SAMPLES,
    APP_VERSION,
    adapted_direction,
    adaptive_consensus_is_recommended,
    adaptive_mode_stats,
    select_adaptive_mode,
)


class AdaptiveInvertPureTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "3.6.1")

    def test_losing_mode_is_inverted_after_enough_samples(self):
        row = {"wins": 34, "losses": 50, "ties": 0, "decided": 84, "win_rate": 34 / 84 * 100}
        info = adaptive_mode_stats(row)
        self.assertTrue(info["inverted"])
        self.assertAlmostEqual(info["raw_win_rate"], 40.4761904762, places=5)
        self.assertAlmostEqual(info["effective_win_rate"], 59.5238095238, places=5)
        self.assertEqual(info["wins"], 50)
        self.assertEqual(info["losses"], 34)
        self.assertEqual(adapted_direction("UP", info), "DOWN")
        self.assertEqual(adapted_direction("DOWN", info), "UP")

    def test_mode_above_half_stays_forward(self):
        row = {"wins": 60, "losses": 40, "ties": 0, "decided": 100, "win_rate": 60.0}
        info = adaptive_mode_stats(row)
        self.assertFalse(info["inverted"])
        self.assertEqual(info["effective_win_rate"], 60.0)
        self.assertEqual(adapted_direction("UP", info), "UP")

    def test_tiny_sample_is_not_flipped(self):
        decided = ADAPTIVE_INVERT_MIN_SAMPLES - 1
        row = {"wins": 1, "losses": decided - 1, "ties": 0, "decided": decided, "win_rate": 100.0 / decided}
        info = adaptive_mode_stats(row)
        self.assertFalse(info["inverted"])

    def test_screenshot_like_stats_choose_pattern_as_best_after_inversion(self):
        stats = {
            "AUTO": {"wins": 35, "losses": 49, "decided": 84, "win_rate": 41.7},
            "M1": {"wins": 38, "losses": 46, "decided": 84, "win_rate": 45.2},
            "M5": {"wins": 35, "losses": 49, "decided": 84, "win_rate": 41.7},
            "AGREE": {"wins": 35, "losses": 49, "decided": 84, "win_rate": 41.7},
            "MOMENTUM": {"wins": 37, "losses": 47, "decided": 84, "win_rate": 44.0},
            "STRUCTURE": {"wins": 36, "losses": 48, "decided": 84, "win_rate": 42.9},
            "WICK": {"wins": 37, "losses": 47, "decided": 84, "win_rate": 44.0},
            "PATTERN": {"wins": 34, "losses": 50, "decided": 84, "win_rate": 40.5},
            "BREAKOUT": {"wins": 36, "losses": 48, "decided": 84, "win_rate": 42.9},
        }
        mode, info = select_adaptive_mode(stats)
        self.assertEqual(mode, "PATTERN")
        self.assertTrue(info["inverted"])
        self.assertAlmostEqual(info["effective_win_rate"], 59.5, places=1)

    def test_buy_now_requires_all_adaptive_votes_same_side(self):
        info = {
            "decided": 84,
            "effective_win_rate": 59.5,
        }
        self.assertTrue(adaptive_consensus_is_recommended("UP", info, "UP", "UP"))
        self.assertFalse(adaptive_consensus_is_recommended("UP", info, "DOWN", "UP"))
        self.assertFalse(adaptive_consensus_is_recommended("UP", info, "UP", "DOWN"))


if __name__ == "__main__":
    unittest.main()
