from __future__ import annotations

import math
from statistics import fmean, pstdev

from models import Candle


def _safe_div(a: float, b: float) -> float:
    return a / b if abs(b) > 1e-12 else 0.0


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def rsi_wilder(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    changes = [b - a for a, b in zip(values, values[1:])]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = fmean(gains[:period])
    avg_loss = fmean(losses[:period])
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((period - 1) * avg_gain + gain) / period
        avg_loss = ((period - 1) * avg_loss + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    ranges = []
    for prev, cur in zip(candles, candles[1:]):
        ranges.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return fmean(ranges[-period:])


def feature_vector(candles: list[Candle], index: int) -> list[float] | None:
    """Đặc trưng chỉ dùng dữ liệu tới index, không nhìn trước tương lai."""
    if index < 25:
        return None
    window = candles[: index + 1]
    current = window[-1]
    closes = [x.close for x in window]
    recent = window[-3:]
    current_atr = atr(window[-20:]) or current.close * 0.0001
    avg_volume = fmean(x.volume for x in window[-20:]) or 1.0
    vector: list[float] = []
    for candle in recent:
        span = max(candle.high - candle.low, candle.close * 1e-9)
        vector.extend([
            _safe_div(candle.close - candle.open, span),
            _safe_div(candle.high - max(candle.open, candle.close), span),
            _safe_div(min(candle.open, candle.close) - candle.low, span),
            _safe_div(candle.close - candle.open, current_atr),
            _safe_div(candle.volume, avg_volume),
        ])
    vector.extend([
        rsi_wilder(closes[-40:]) / 100.0,
        _safe_div(ema(closes[-30:], 9) - ema(closes[-30:], 21), current_atr),
        _safe_div(current.close - fmean(closes[-20:]), current_atr),
    ])
    return vector


def _distance(a: list[float], b: list[float], scales: list[float]) -> float:
    return math.sqrt(sum(((x - y) / s) ** 2 for x, y, s in zip(a, b, scales)))


def knn_probability(candles: list[Candle], horizon: int, neighbors: int = 100) -> tuple[float, int]:
    """Xác suất giá sau horizon nến cao hơn close tại mẫu lịch sử."""
    if len(candles) < 80 + horizon:
        return 0.5, 0
    query_index = len(candles) - 1
    query = feature_vector(candles, query_index)
    if query is None:
        return 0.5, 0
    samples: list[tuple[list[float], int]] = []
    for i in range(25, query_index - horizon):
        features = feature_vector(candles, i)
        if features is not None:
            outcome = int(candles[i + horizon].close > candles[i].close)
            samples.append((features, outcome))
    if len(samples) < 30:
        return 0.5, len(samples)
    columns = list(zip(*(features for features, _ in samples)))
    scales = [pstdev(col) or 1.0 for col in columns]
    ranked = sorted((_distance(query, features, scales), outcome) for features, outcome in samples)
    selected = ranked[: min(neighbors, len(ranked))]
    weights = [1.0 / (distance + 0.05) for distance, _ in selected]
    probability = sum(w * outcome for w, (_, outcome) in zip(weights, selected)) / sum(weights)
    return probability, len(selected)


def blended_prediction(m1: list[Candle], m5: list[Candle], live_price: float, target: float) -> tuple[str, float, float, float, int]:
    p1, n1 = knn_probability(m1, horizon=5)
    p5, n5 = knn_probability(m5, horizon=1)
    volatility = atr(m1[-30:]) or max(target * 0.0001, 1.0)
    target_edge = max(-1.0, min(1.0, (live_price - target) / (2.0 * volatility)))
    probability_up = max(0.02, min(0.98, 0.55 * p1 + 0.35 * p5 + 0.10 * (0.5 + target_edge / 2)))
    direction = "UP" if probability_up >= 0.5 else "DOWN"
    confidence = probability_up if direction == "UP" else 1.0 - probability_up
    return direction, confidence, p1, p5, min(n1, n5)

