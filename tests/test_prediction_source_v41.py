from __future__ import annotations

import inspect
import unittest

from prediction_source import GREEN, RED, PredictionHistorySource, parse_prediction_resolution
from runtime_v4 import PatternSignalBot


class PredictionSourceV41Tests(unittest.TestCase):
    def test_winner_up_is_green(self):
        payload = {
            "data": {
                "markets": [{
                    "tradingStatus": "RESOLVED",
                    "resolution": {"winningOutcome": "Up"},
                    "outcomes": [{"name": "Up"}, {"name": "Down"}],
                }]
            }
        }
        self.assertEqual(parse_prediction_resolution(payload), GREEN)

    def test_winner_down_is_red(self):
        payload = {
            "data": {
                "markets": [{
                    "tradingStatus": "SETTLED",
                    "resolution": {"winner": "Down"},
                    "outcomes": [{"name": "Up"}, {"name": "Down"}],
                }]
            }
        }
        self.assertEqual(parse_prediction_resolution(payload), RED)

    def test_payouts_follow_outcome_names(self):
        payload = {
            "data": {
                "markets": [{
                    "tradingStatus": "CLOSED",
                    "resolution": {"payouts": [0, 1]},
                    "outcomes": [{"name": "Up"}, {"name": "Down"}],
                }]
            }
        }
        self.assertEqual(parse_prediction_resolution(payload), RED)

    def test_open_market_is_not_guessed(self):
        payload = {
            "data": {
                "markets": [{
                    "tradingStatus": "OPEN",
                    "resolution": None,
                    "outcomes": [
                        {"name": "Up", "bestAsk": {"price": "0.99"}},
                        {"name": "Down", "bestAsk": {"price": "0.01"}},
                    ],
                }]
            }
        }
        self.assertIsNone(parse_prediction_resolution(payload))

    def test_slug_matches_binance_prediction_style(self):
        self.assertEqual(
            PredictionHistorySource.slug(1785734400),
            "btc-updown-5m-1785734400",
        )

    def test_runtime_defaults_to_prediction_source_path(self):
        source = inspect.getsource(PatternSignalBot._fetch_closed)
        self.assertIn('prediction_source == "predictfun"', source)
        self.assertIn("prediction_history.recent", source)

    def test_runtime_has_manual_telegram_test(self):
        self.assertTrue(hasattr(PatternSignalBot, "test_telegram"))


if __name__ == "__main__":
    unittest.main()
