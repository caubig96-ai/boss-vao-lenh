from __future__ import annotations

import unittest

from candle_color_model import (
    ENSEMBLE_WEIGHTS,
    candle_shape,
    candle_token,
    predict_next_color,
    sequence_probability,
)
from models import Candle
from runtime_v37 import APP_VERSION, recommendation_from_forecast


def make_candle(index: int, green: bool, *, strong: bool = True, volume: float = 100.0) -> Candle:
    open_time = index * 300_000
    open_price = 100.0 + index * 0.01
    move = 1.0 if strong else 0.2
    close_price = open_price + move if green else open_price - move
    high = max(open_price, close_price) + 0.15
    low = min(open_price, close_price) - 0.15
    return Candle("5m", open_time, open_time + 299_999, open_price, high, low, close_price, volume, True)


class CandleColorPureTests(unittest.TestCase):
    def test_version_and_weights(self):
        self.assertEqual(APP_VERSION, "3.7.0")
        self.assertAlmostEqual(sum(ENSEMBLE_WEIGHTS.values()), 1.0, places=9)

    def test_shape_and_color_are_scale_free(self):
        green = Candle("5m", 0, 299_999, 100, 112, 98, 110, 10, True)
        shape = candle_shape(green)
        self.assertEqual(candle_token(green), 1)
        self.assertGreater(shape["signed_body"], 0)
        self.assertGreater(shape["close_position"], 0.5)
        self.assertGreaterEqual(shape["lower_wick"], 0)
        self.assertGreaterEqual(shape["upper_wick"], 0)

    def test_sequence_learns_empirical_next_color_not_hardcoded_rule(self):
        # Repeat RED,GREEN -> GREEN. The current suffix RED,GREEN should therefore
        # have a historical GREEN continuation more often than RED.
        history = []
        index = 0
        for _ in range(60):
            for color in (False, True, True):
                history.append(make_candle(index, color))
                index += 1
        # End on RED,GREEN so the queried suffix is represented many times before.
        history.extend([make_candle(index, False), make_candle(index + 1, True)])
        probability, samples, by_length = sequence_probability(history)
        self.assertGreater(samples, 10)
        self.assertGreater(probability, 0.55)
        self.assertTrue(by_length)

    def test_full_engine_prefers_green_on_persistent_green_history(self):
        history = [make_candle(i, True, strong=True, volume=100 + i) for i in range(180)]
        forecast = predict_next_color(history)
        self.assertEqual(forecast.direction, "UP")
        self.assertGreater(forecast.green_probability, 0.55)
        self.assertGreaterEqual(forecast.agreement, 4)
        self.assertGreaterEqual(forecast.knn_samples, 20)

    def test_model_boundary_accepts_only_closed_history(self):
        closed = [make_candle(i, i % 3 != 0) for i in range(180)]
        live = make_candle(181, False)
        live.closed = False
        base = predict_next_color(closed)
        with_live_object = predict_next_color(closed + [live])
        # An accidentally supplied live candle is discarded, so it cannot leak.
        self.assertEqual(base.direction, with_live_object.direction)
        self.assertAlmostEqual(base.green_probability, with_live_object.green_probability, places=12)

    def test_recommendation_requires_consensus_and_calibration_or_strict_warmup(self):
        history = [make_candle(i, True, strong=True, volume=100 + i) for i in range(240)]
        forecast = predict_next_color(history)
        # Strong warm-up may pass only if the raw engine itself reaches the strict
        # confidence/consensus thresholds.
        weak_calibration = {"decided": 0, "win_rate": 0.0}
        warmup = recommendation_from_forecast(forecast, weak_calibration)
        if forecast.confidence < 0.65 or forecast.agreement < 5:
            self.assertFalse(warmup)

        mature_bad = {"decided": 50, "win_rate": 49.0}
        self.assertFalse(recommendation_from_forecast(forecast, mature_bad))

        mature_good = {"decided": 50, "win_rate": 62.0}
        if (
            forecast.confidence >= 0.60
            and forecast.agreement >= 5
            and forecast.knn_samples >= 30
            and forecast.sequence_samples >= 12
        ):
            self.assertTrue(recommendation_from_forecast(forecast, mature_good))


if __name__ == "__main__":
    unittest.main()
