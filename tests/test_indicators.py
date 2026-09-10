import unittest

from indicators import (
    blended_prediction,
    candle_analysis,
    feature_vector,
    five_candle_pattern_probability,
    rsi_wilder,
)
from models import Candle


def candles(interval: str, count: int, rising: bool = True):
    result = []
    price = 100.0
    step = 0.2 if rising else -0.2
    width = 60_000 if interval == "1m" else 300_000
    for i in range(count):
        close = price + step
        result.append(Candle(interval, i * width, (i + 1) * width - 1, price,
                             max(price, close) + 0.1, min(price, close) - 0.1,
                             close, 100 + i % 7, True))
        price = close
    return result


class IndicatorTests(unittest.TestCase):
    def test_rsi_rising(self):
        self.assertGreater(rsi_wilder(list(range(30))), 90)

    def test_feature_has_fixed_length(self):
        self.assertEqual(len(feature_vector(candles("1m", 40), 39)), 18)

    def test_five_candle_pattern_probability(self):
        probability, samples = five_candle_pattern_probability(candles("5m", 200))
        self.assertGreater(samples, 0)
        self.assertGreaterEqual(probability, 0.02)
        self.assertLessEqual(probability, 0.98)

    def test_prediction_shape(self):
        result = blended_prediction(candles("1m", 200), candles("5m", 200), 140, 139)
        self.assertIn(result[0], ("UP", "DOWN"))
        self.assertGreaterEqual(result[1], 0.5)

    def test_candle_analysis_contains_context(self):
        text = candle_analysis(candles("1m", 40), "M1")
        self.assertIn("M1:", text)
        self.assertIn("RSI", text)
        self.assertIn("EMA9", text)


if __name__ == "__main__":
    unittest.main()
