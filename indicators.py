from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean, pstdev

from models import Candle


M1_CONTEXT_24H = 24 * 60
M5_PATTERN_24H = 24 * 60 // 5
PATTERN_WINDOW = 5
M1_TREND_WINDOW = 10
M5_TREND_WINDOW = 5

ANALYSIS_MODE_LABELS = {
    "AUTO": "CÂN BẰNG",
    "M1": "M1 NHANH",
    "M5": "M5 CHẮC",
    "AGREE": "ĐỒNG THUẬN M1+M5",
}

ANALYSIS_MODE_WEIGHTS = {
    # m1, m5, historical pattern, agreement multiplier
    "AUTO": (0.50, 0.30, 0.20, 1.00),
    "M1": (0.70, 0.20, 0.10, 0.75),
    "M5": (0.25, 0.55, 0.20, 1.00),
    "AGREE": (0.40, 0.35, 0.25, 1.50),
}


def normalize_analysis_mode(mode: str | None) -> str:
    value = (mode or "AUTO").strip().upper()
    return value if value in ANALYSIS_MODE_WEIGHTS else "AUTO"


def analysis_mode_label(mode: str | None) -> str:
    return ANALYSIS_MODE_LABELS[normalize_analysis_mode(mode)]


def _safe_div(a: float, b: float) -> float:
    return a / b if abs(b) > 1e-12 else 0.0


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _sign(value: float, eps: float = 1e-12) -> float:
    if value > eps:
        return 1.0
    if value < -eps:
        return -1.0
    return 0.0


@dataclass(frozen=True, slots=True)
class TrendSnapshot:
    """Tóm tắt hướng của một cụm nến ĐÃ ĐÓNG, score nằm trong [-1, 1]."""

    score: float
    probability_up: float
    bullish: int
    bearish: int
    doji: int
    body_imbalance: float
    close_slope: float
    structure: float
    wick_pressure: float
    used: int

    @property
    def direction(self) -> str:
        if self.score > 0.08:
            return "UP"
        if self.score < -0.08:
            return "DOWN"
        return "FLAT"


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


def _recency_weights(count: int) -> list[float]:
    """10 nến M1: nửa gần nhất chiếm xấp xỉ 60% tổng trọng số."""
    if count <= 1:
        return [1.0] * count
    return [1.0 + 1.2 * i / (count - 1) for i in range(count)]


def timeframe_trend(candles: list[Candle], window: int) -> TrendSnapshot:
    """Đọc xu hướng trực tiếp từ các nến đã đóng gần nhất.

    Điểm gồm: 25% màu nến, 35% lực thân, 20% dốc close,
    15% cấu trúc high/low và 5% áp lực râu nến. Nến gần nhất
    có trọng số lớn hơn để bắt đảo chiều nhanh hơn.
    """
    series = [c for c in candles if c.closed][-window:]
    count = len(series)
    if count < 2:
        return TrendSnapshot(0.0, 0.5, 0, 0, count, 0.0, 0.0, 0.0, 0.0, count)

    weights = _recency_weights(count)
    color_numerator = 0.0
    color_denominator = 0.0
    signed_body = 0.0
    absolute_body = 0.0
    wick_sum = 0.0
    wick_weight = 0.0
    ranges: list[float] = []
    bullish = bearish = doji = 0

    for candle, weight in zip(series, weights):
        span = max(candle.high - candle.low, abs(candle.close) * 1e-9)
        ranges.append(span)
        body_delta = candle.close - candle.open
        body = abs(body_delta)
        body_ratio = body / span

        if body_ratio <= 0.08:
            candle_sign = 0.0
            doji += 1
        elif body_delta > 0:
            candle_sign = 1.0
            bullish += 1
        else:
            candle_sign = -1.0
            bearish += 1

        color_numerator += weight * candle_sign
        color_denominator += weight
        signed_body += weight * body_delta
        absolute_body += weight * body

        upper = candle.high - max(candle.open, candle.close)
        lower = min(candle.open, candle.close) - candle.low
        wick_sum += weight * _safe_div(lower - upper, span)
        wick_weight += weight

    color_score = _safe_div(color_numerator, color_denominator)
    body_imbalance = _clamp(_safe_div(signed_body, absolute_body))

    average_range = fmean(ranges) or max(abs(series[-1].close) * 1e-9, 1e-9)
    net_close_move = series[-1].close - series[0].close
    close_slope = _clamp(_safe_div(net_close_move, average_range * max(1, count - 1)))

    structure_sum = 0.0
    structure_weight = 0.0
    pair_weights = weights[1:]
    for previous, current, weight in zip(series, series[1:], pair_weights):
        high_step = _sign(current.high - previous.high)
        low_step = _sign(current.low - previous.low)
        structure_sum += weight * ((high_step + low_step) / 2.0)
        structure_weight += weight
    structure = _clamp(_safe_div(structure_sum, structure_weight))
    wick_pressure = _clamp(_safe_div(wick_sum, wick_weight))

    score = _clamp(
        0.25 * color_score
        + 0.35 * body_imbalance
        + 0.20 * close_slope
        + 0.15 * structure
        + 0.05 * wick_pressure
    )
    probability_up = _clamp(0.5 + 0.45 * score, 0.05, 0.95)
    return TrendSnapshot(
        score,
        probability_up,
        bullish,
        bearish,
        doji,
        body_imbalance,
        close_slope,
        structure,
        wick_pressure,
        count,
    )


def m1_trend_score(candles: list[Candle]) -> TrendSnapshot:
    return timeframe_trend(candles, M1_TREND_WINDOW)


def m5_trend_score(candles: list[Candle]) -> TrendSnapshot:
    return timeframe_trend(candles, M5_TREND_WINDOW)


def timeframe_agreement(m1: TrendSnapshot, m5: TrendSnapshot) -> tuple[str, float]:
    """Trả về hướng đồng thuận và bonus tối đa 0.10 cho score cuối."""
    if abs(m1.score) < 0.12 or abs(m5.score) < 0.12:
        return "MIXED", 0.0
    if m1.score > 0 and m5.score > 0:
        strength = min(1.0, (abs(m1.score) + abs(m5.score)) / 2.0)
        return "UP", 0.10 * strength
    if m1.score < 0 and m5.score < 0:
        strength = min(1.0, (abs(m1.score) + abs(m5.score)) / 2.0)
        return "DOWN", -0.10 * strength
    return "CONFLICT", 0.0


def trend_summary(snapshot: TrendSnapshot, label: str) -> str:
    direction = {"UP": "TĂNG", "DOWN": "GIẢM", "FLAT": "ĐI NGANG"}[snapshot.direction]
    return (
        f"{label}: {direction} | xanh {snapshot.bullish}/{snapshot.used}, "
        f"đỏ {snapshot.bearish}/{snapshot.used}, doji {snapshot.doji}/{snapshot.used} | "
        f"lực thân {snapshot.body_imbalance:+.2f} | dốc close {snapshot.close_slope:+.2f}"
    )


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
    """So 5 nến M5 vừa đóng với các nhóm 5 nến trước đó trong cửa sổ rolling 24 giờ."""
    series = [c for c in candles if c.closed][-history_candles:]
    if len(series) < PATTERN_WINDOW * 3:
        return 0.5, 0

    query_start = len(series) - PATTERN_WINDOW
    query = five_candle_pattern_vector(series[query_start:])
    if query is None:
        return 0.5, 0

    samples: list[tuple[list[float], int]] = []
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


def blended_prediction(
    m1: list[Candle],
    m5: list[Candle],
    live_price: float,
    target: float,
    mode: str = "AUTO",
) -> tuple[str, float, float, float, int]:
    """Chọn hướng theo chế độ phân tích nhưng luôn trả một quyết định mỗi phiên M5.

    AUTO  : 50% M1 + 30% M5 + 20% pattern, cân bằng phản ứng/xác nhận.
    M1    : 70% M1 + 20% M5 + 10% pattern, phản ứng nhanh hơn.
    M5    : 25% M1 + 55% M5 + 20% pattern, ưu tiên xu hướng M5.
    AGREE : 40% M1 + 35% M5 + 25% pattern, thưởng đồng thuận M1/M5 mạnh hơn.

    Chỉ nến đã đóng được dùng trong trend/pattern. live_price/target được giữ trong
    chữ ký để tương thích runtime nhưng không được đưa vào feature xu hướng.
    """
    del live_price, target
    selected_mode = normalize_analysis_mode(mode)
    m1_weight, m5_weight, pattern_weight, agreement_multiplier = ANALYSIS_MODE_WEIGHTS[selected_mode]

    m1_trend = m1_trend_score(m1)
    m5_trend = m5_trend_score(m5)
    pattern_probability, pattern_samples = five_candle_pattern_probability(m5)
    pattern_score = _clamp((pattern_probability - 0.5) * 2.0)
    _, agreement_bonus = timeframe_agreement(m1_trend, m5_trend)

    combined_score = _clamp(
        m1_weight * m1_trend.score
        + m5_weight * m5_trend.score
        + pattern_weight * pattern_score
        + agreement_bonus * agreement_multiplier
    )
    probability_up = _clamp(0.5 + 0.45 * combined_score, 0.05, 0.95)
    direction = "UP" if probability_up >= 0.5 else "DOWN"
    confidence = probability_up if direction == "UP" else 1.0 - probability_up
    return (
        direction,
        confidence,
        m1_trend.probability_up,
        m5_trend.probability_up,
        pattern_samples,
    )


def candle_analysis(candles: list[Candle], label: str) -> str:
    """Mô tả ngắn nến vừa đóng và bối cảnh kỹ thuật, không dùng nến live."""
    closed = [c for c in candles if c.closed]
    if not closed:
        return f"{label}: chưa đủ dữ liệu"
    last = closed[-1]
    span = max(last.high - last.low, last.close * 1e-9)
    body = abs(last.close - last.open)
    upper = last.high - max(last.open, last.close)
    lower = min(last.open, last.close) - last.low
    closes = [c.close for c in closed[-40:]]
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
