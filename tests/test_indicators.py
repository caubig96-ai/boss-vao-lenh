import unittest

from indicators import (
    blended_prediction,
    candle_analysis,
    feature_vector,
    five_candle_pattern_probability,
    m1_trend_score,
    m5_trend_score,
    rsi_wilder,
    timeframe_agreement,
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


def green_count_but_bearish_force(interval: str = "1m"):
    """8 nến xanh rất nhỏ nhưng 2 nến đỏ lớn: không được chọn tăng chỉ vì đếm màu."""
    width = 60_000 if interval == "1m" else 300_000
    result = []
    price = 100.0
    moves = [0.05] * 4 + [-1.5] + [0.05] * 4 + [-1.5]
    for i, move in enumerate(moves):
        close = price + move
        wick = 0.02 if move > 0 else 0.08
        result.append(Candle(
            interval,
            i * width,
            (i + 1) * width - 1,
            price,
            max(price, close) + wick,
            min(price, close) - wick,
            close,
            100.0,
            True,
        ))
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

    def test_m1_last_ten_closed_candles_detect_rising_trend(self):
        trend = m1_trend_score(candles("1m", 30, rising=True))
        self.assertEqual(trend.used, 10)
        self.assertEqual(trend.bullish, 10)
        self.assertEqual(trend.bearish, 0)
        self.assertGreater(trend.score, 0.5)
        self.assertGreater(trend.probability_up, 0.70)
        self.assertEqual(trend.direction, "UP")

    def test_m5_last_five_closed_candles_detect_falling_trend(self):
        trend = m5_trend_score(candles("5m", 30, rising=False))
        self.assertEqual(trend.used, 5)
        self.assertEqual(trend.bearish, 5)
        self.assertLess(trend.score, -0.5)
        self.assertLess(trend.probability_up, 0.30)
        self.assertEqual(trend.direction, "DOWN")

    def test_body_force_can_override_green_candle_count(self):
        trend = m1_trend_score(green_count_but_bearish_force())
        self.assertEqual(trend.bullish, 8)
        self.assertEqual(trend.bearish, 2)
        self.assertLess(trend.body_imbalance, 0)
        self.assertLess(trend.score, 0)
        self.assertEqual(trend.direction, "DOWN")

    def test_live_candle_is_never_used_in_trend_features(self):
        history = candles("1m", 20, rising=True)
        baseline = m1_trend_score(history)
        live = Candle("1m", 20 * 60_000, 21 * 60_000 - 1,
                      104.0, 104.0, 90.0, 90.0, 9999.0, False)
        with_live = m1_trend_score(history + [live])
        self.assertAlmostEqual(with_live.score, baseline.score)
        self.assertEqual(with_live.bullish, baseline.bullish)
        self.assertEqual(with_live.bearish, baseline.bearish)

    def test_timeframe_agreement_rewards_same_direction(self):
        m1 = m1_trend_score(candles("1m", 30, rising=True))
        m5 = m5_trend_score(candles("5m", 30, rising=True))
        direction, bonus = timeframe_agreement(m1, m5)
        self.assertEqual(direction, "UP")
        self.assertGreater(bonus, 0)

    def test_timeframe_conflict_gets_no_bonus(self):
        m1 = m1_trend_score(candles("1m", 30, rising=True))
        m5 = m5_trend_score(candles("5m", 30, rising=False))
        direction, bonus = timeframe_agreement(m1, m5)
        self.assertEqual(direction, "CONFLICT")
        self.assertEqual(bonus, 0.0)

    def test_prediction_prefers_up_when_m1_and_m5_agree_up(self):
        result = blended_prediction(candles("1m", 200, True), candles("5m", 200, True), 140, 139)
        self.assertEqual(result[0], "UP")
        self.assertGreater(result[1], 0.60)
        self.assertGreater(result[2], 0.5)
        self.assertGreater(result[3], 0.5)

    def test_prediction_prefers_down_when_m1_and_m5_agree_down(self):
        result = blended_prediction(candles("1m", 200, False), candles("5m", 200, False), 60, 61)
        self.assertEqual(result[0], "DOWN")
        self.assertGreater(result[1], 0.60)
        self.assertLess(result[2], 0.5)
        self.assertLess(result[3], 0.5)

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
