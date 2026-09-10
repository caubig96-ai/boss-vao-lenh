from __future__ import annotations

import math
from statistics import fmean, pstdev

from models import Candle


M1_CONTEXT_24H = 24 * 60
M5_PATTERN_24H = 24 * 60 // 5
PATTERN_WINDOW = 5


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


def five_candle_pattern_vector(window: list[Candle]) -> list[float] | None:
    """Mô tả hình dạng và nhịp chuyển động của đúng 5 nến, độc lập mức giá tuyệt đối."""
    if len(window) != PATTERN_WINDOW:
        return None
    ranges = [max(c.high - c.low, abs(c.close) * 1e-9) for c in window]
    average_range = fmean(ranges) or 1.0
    average_volume = fmean(c.volume for c in window) or 1.0
    previous_close = window[0].open
    vector: list[float] = []
    for candle, span in zip(window, ranges):
        vector.extend([
            _safe_div(candle.close - candle.open, span),
            _safe_div(candle.high - max(candle.open, candle.close), span),
            _safe_div(min(candle.open, candle.close) - candle.low, span),
            _safe_div(span, average_range),
            _safe_div(candle.close - previous_close, average_range),
            _safe_div(candle.volume, average_volume),
        ])
        previous_close = candle.close
    return vector


def five_candle_pattern_probability(
    candles: list[Candle],
    history_candles: int = M5_PATTERN_24H,
    neighbors: int = 40,
) -> tuple[float, int]:
    """So 5 nến M5 vừa đóng với các nhóm 5 nến trước đó trong cửa sổ rolling 24 giờ.

    Mỗi mẫu lịch sử chỉ được gắn nhãn bằng hướng của cây nến kế tiếp sau mẫu đó,
    vì vậy không dùng dữ liệu tương lai của phiên đang dự đoán.
    """
    series = candles[-history_candles:]
    if len(series) < PATTERN_WINDOW * 3:
        return 0.5, 0

    query_start = len(series) - PATTERN_WINDOW
    query = five_candle_pattern_vector(series[query_start:])
    if query is None:
        return 0.5, 0

    samples: list[tuple[list[float], int]] = []
    # end tối đa query_start - 1: mẫu lịch sử không chồng lên 5 nến query.
    for end in range(PATTERN_WINDOW - 1, query_start):
        window = series[end - PATTERN_WINDOW + 1: end + 1]
        features = five_candle_pattern_vector(window)
        if features is None:
            continue
        next_candle = series[end + 1]
        outcome = int(next_candle.close > next_candle.open)
        samples.append((features, outcome))

    if len(samples) < 10:
        return 0.5, len(samples)

    columns = list(zip(*(features for features, _ in samples)))
    scales = [pstdev(column) or 1.0 for column in columns]
    ranked = sorted((_distance(query, features, scales), outcome) for features, outcome in samples)
    selected = ranked[: min(neighbors, len(ranked))]
    weights = [1.0 / (distance + 0.10) for distance, _ in selected]
    probability = sum(weight * outcome for weight, (_, outcome) in zip(weights, selected)) / sum(weights)
    return max(0.02, min(0.98, probability)), len(selected)


def blended_prediction(m1: list[Candle], m5: list[Candle], live_price: float, target: float) -> tuple[str, float, float, float, int]:
    # M1 chỉ lấy tối đa 24 giờ làm bối cảnh phụ. Trọng số chính là mẫu 5 nến M5
    # trong đúng cửa sổ rolling 24 giờ (288 nến M5).
    p1, _ = knn_probability(m1[-M1_CONTEXT_24H:], horizon=5, neighbors=80)
    pattern_probability, pattern_samples = five_candle_pattern_probability(m5)
    volatility = atr(m1[-30:]) or max(target * 0.0001, 1.0)
    target_edge = max(-1.0, min(1.0, (live_price - target) / (2.0 * volatility)))
    probability_up = max(
        0.02,
        min(0.98, 0.25 * p1 + 0.65 * pattern_probability + 0.10 * (0.5 + target_edge / 2)),
    )
    direction = "UP" if probability_up >= 0.5 else "DOWN"
    confidence = probability_up if direction == "UP" else 1.0 - probability_up
    return direction, confidence, p1, pattern_probability, pattern_samples


def candle_analysis(candles: list[Candle], label: str) -> str:
    """Mô tả ngắn nến vừa đóng và bối cảnh kỹ thuật, không dùng nến live."""
    if not candles:
        return f"{label}: chưa đủ dữ liệu"
    last = candles[-1]
    span = max(last.high - last.low, last.close * 1e-9)
    body = abs(last.close - last.open)
    upper = last.high - max(last.open, last.close)
    lower = min(last.open, last.close) - last.low
    closes = [c.close for c in candles[-40:]]
    current_rsi = rsi_wilder(closes)
    fast = ema(closes, 9)
    slow = ema(closes, 21)

    if body / span <= 0.12:
        shape = "Doji, thị trường đang giằng co"
    elif lower > body * 2 and upper < body:
        shape = "râu dưới dài, có lực mua đẩy lên"
    elif upper > body * 2 and lower < body:
        shape = "râu trên dài, có lực bán ép xuống"
    elif last.close > last.open:
        shape = "nến tăng"
    else:
        shape = "nến giảm"

    trend = "EMA9 trên EMA21" if fast >= slow else "EMA9 dưới EMA21"
    return f"{label}: {shape}; RSI {current_rsi:.1f}; {trend}"
