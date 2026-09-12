from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from statistics import median

from models import Candle


EPS = 1e-12
ENSEMBLE_WEIGHTS = {
    "knn": 0.30,
    "sequence": 0.20,
    "body": 0.20,
    "close_position": 0.12,
    "wick": 0.10,
    "regime": 0.08,
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def candle_token(candle: Candle) -> int:
    """1=green, -1=red, 0=doji."""
    if candle.close > candle.open:
        return 1
    if candle.close < candle.open:
        return -1
    return 0


def candle_shape(candle: Candle) -> dict[str, float]:
    """Scale-free OHLC shape features. No future/live information is required."""
    span = max(float(candle.high) - float(candle.low), EPS)
    body = float(candle.close) - float(candle.open)
    upper = float(candle.high) - max(float(candle.open), float(candle.close))
    lower = min(float(candle.open), float(candle.close)) - float(candle.low)
    return {
        "signed_body": clamp(body / span, -1.0, 1.0),
        "body_ratio": clamp(abs(body) / span, 0.0, 1.0),
        "upper_wick": clamp(upper / span, 0.0, 1.0),
        "lower_wick": clamp(lower / span, 0.0, 1.0),
        "close_position": clamp((float(candle.close) - float(candle.low)) / span, 0.0, 1.0),
        "range_pct": span / max(abs(float(candle.open)), EPS),
        "volume": max(0.0, float(candle.volume)),
    }


def _recent_weights(count: int, half_life: float = 2.0) -> list[float]:
    if count <= 0:
        return []
    return [0.5 ** ((count - 1 - index) / max(half_life, EPS)) for index in range(count)]


def _weighted_average(values: list[float], weights: list[float]) -> float:
    total = sum(weights)
    if total <= EPS or not values:
        return 0.0
    return sum(value * weight for value, weight in zip(values, weights)) / total


def body_probability(history: list[Candle], lookback: int = 5) -> float:
    candles = history[-lookback:]
    if not candles:
        return 0.5
    values = [candle_shape(c)["signed_body"] for c in candles]
    score = _weighted_average(values, _recent_weights(len(values), 2.0))
    return clamp(0.5 + 0.35 * score, 0.10, 0.90)


def close_position_probability(history: list[Candle], lookback: int = 5) -> float:
    candles = history[-lookback:]
    if not candles:
        return 0.5
    values = [2.0 * candle_shape(c)["close_position"] - 1.0 for c in candles]
    score = _weighted_average(values, _recent_weights(len(values), 2.0))
    return clamp(0.5 + 0.30 * score, 0.15, 0.85)


def wick_probability(history: list[Candle], lookback: int = 5) -> float:
    candles = history[-lookback:]
    if not candles:
        return 0.5
    # Long lower wick is buying rejection (bullish); long upper wick is selling rejection.
    values = []
    for candle in candles:
        shape = candle_shape(candle)
        values.append(shape["lower_wick"] - shape["upper_wick"])
    score = _weighted_average(values, _recent_weights(len(values), 2.0))
    return clamp(0.5 + 0.30 * score, 0.15, 0.85)


def regime_probability(history: list[Candle], lookback: int = 12) -> float:
    candles = history[-lookback:]
    if len(candles) < 4:
        return 0.5
    ranges = [max(c.high - c.low, EPS) for c in candles]
    avg_range = sum(ranges) / len(ranges)
    net = candles[-1].close - candles[0].close
    trend = clamp(net / max(avg_range * math.sqrt(len(candles)), EPS), -1.0, 1.0)

    structure_points = 0.0
    comparisons = 0
    for previous, current in zip(candles, candles[1:]):
        if current.high > previous.high:
            structure_points += 1.0
        elif current.high < previous.high:
            structure_points -= 1.0
        if current.low > previous.low:
            structure_points += 1.0
        elif current.low < previous.low:
            structure_points -= 1.0
        comparisons += 2
    structure = structure_points / max(comparisons, 1)
    return clamp(0.5 + 0.18 * trend + 0.12 * structure, 0.15, 0.85)


def sequence_probability(history: list[Candle]) -> tuple[float, int, dict[int, int]]:
    """Empirical next-color probability after exact 2..5 color patterns.

    Only previously closed candles are accepted. Each historical occurrence uses
    the color of its already-closed following candle as the label. Recent examples
    receive more weight, while longer patterns receive more weight only when they
    have enough matches.
    """
    tokens = [candle_token(c) for c in history]
    if len(tokens) < 8:
        return 0.5, 0, {}

    pattern_weights = {2: 0.10, 3: 0.20, 4: 0.30, 5: 0.40}
    probabilities: list[tuple[float, float]] = []
    total_samples = 0
    by_length: dict[int, int] = {}
    last_label_index = len(tokens) - 1

    for length, base_weight in pattern_weights.items():
        if len(tokens) <= length:
            continue
        target = tokens[-length:]
        if 0 in target:
            continue
        green_weight = 0.0
        observed_weight = 0.0
        samples = 0
        for end in range(length - 1, len(tokens) - 1):
            start = end - length + 1
            if tokens[start:end + 1] != target:
                continue
            label = tokens[end + 1]
            if label == 0:
                continue
            age = max(0, last_label_index - (end + 1))
            recency = 0.5 ** (age / 2016.0)  # ~7 days of M5 candles per half-life.
            observed_weight += recency
            green_weight += recency if label == 1 else 0.0
            samples += 1
        if samples <= 0:
            continue
        # Beta(1,1) prior limits extreme rates from tiny samples.
        probability = (green_weight + 1.0) / (observed_weight + 2.0)
        reliability = min(1.0, samples / 20.0)
        probabilities.append((probability, base_weight * reliability))
        total_samples += samples
        by_length[length] = samples

    if not probabilities:
        return 0.5, 0, by_length
    weight_sum = sum(weight for _probability, weight in probabilities)
    if weight_sum <= EPS:
        return 0.5, total_samples, by_length
    result = sum(probability * weight for probability, weight in probabilities) / weight_sum
    return clamp(result, 0.05, 0.95), total_samples, by_length


def _window_vector(window: list[Candle]) -> list[float]:
    shapes = [candle_shape(c) for c in window]
    median_range = max(median([shape["range_pct"] for shape in shapes]), EPS)
    positive_volumes = [shape["volume"] for shape in shapes if shape["volume"] > 0]
    median_volume = max(median(positive_volumes), EPS) if positive_volumes else 1.0
    vector: list[float] = []
    for shape in shapes:
        range_rel = clamp(math.log(max(shape["range_pct"], EPS) / median_range), -2.0, 2.0) / 2.0
        if shape["volume"] > 0:
            volume_rel = clamp(math.log(max(shape["volume"], EPS) / median_volume), -3.0, 3.0) / 3.0
        else:
            volume_rel = 0.0
        vector.extend([
            shape["signed_body"],
            shape["body_ratio"],
            2.0 * shape["close_position"] - 1.0,
            shape["lower_wick"] - shape["upper_wick"],
            range_rel,
            volume_rel,
        ])
    return vector


def _vector_distance(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return float("inf")
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)) / len(left))


def knn_probability(
    history: list[Candle],
    window_size: int = 5,
    neighbors: int = 80,
    minimum_neighbors: int = 20,
) -> tuple[float, int, float]:
    """Find historical candle-shape windows most similar to the latest window."""
    if len(history) < window_size + minimum_neighbors + 1:
        return 0.5, 0, float("inf")
    target = _window_vector(history[-window_size:])
    candidates: list[tuple[float, int, int]] = []
    last_index = len(history) - 1

    # Candidate window must have one already-closed candle after it for a label.
    for end in range(window_size - 1, len(history) - 1):
        label = candle_token(history[end + 1])
        if label == 0:
            continue
        window = history[end - window_size + 1:end + 1]
        distance = _vector_distance(target, _window_vector(window))
        if math.isfinite(distance):
            candidates.append((distance, end, label))

    if len(candidates) < minimum_neighbors:
        return 0.5, len(candidates), float("inf")
    nearest = heapq.nsmallest(min(neighbors, len(candidates)), candidates, key=lambda item: item[0])
    weighted_green = 0.0
    total_weight = 0.0
    distances: list[float] = []
    for distance, end, label in nearest:
        age = max(0, last_index - (end + 1))
        recency = 0.5 ** (age / 2016.0)
        similarity = 1.0 / (0.05 + distance)
        weight = recency * similarity
        total_weight += weight
        weighted_green += weight if label == 1 else 0.0
        distances.append(distance)

    # Small neutral prior prevents a few ultra-close examples from becoming 0/100%.
    probability = (weighted_green + 1.0) / (total_weight + 2.0)
    mean_distance = sum(distances) / len(distances) if distances else float("inf")
    return clamp(probability, 0.05, 0.95), len(nearest), mean_distance


@dataclass(slots=True)
class ColorForecast:
    direction: str
    green_probability: float
    confidence: float
    agreement: int
    components: dict[str, float]
    sequence_samples: int
    sequence_by_length: dict[int, int]
    knn_samples: int
    knn_mean_distance: float

    @property
    def color(self) -> str:
        return "XANH" if self.direction == "UP" else "ĐỎ"


def predict_next_color(history: list[Candle]) -> ColorForecast:
    """Predict the next M5 candle color from CLOSED history only.

    This function intentionally has no live_price/current-candle argument, making
    future/live leakage impossible at the model boundary.
    """
    closed = [c for c in history if c.closed]
    sequence_p, sequence_samples, by_length = sequence_probability(closed)
    knn_p, knn_samples, mean_distance = knn_probability(closed)
    components = {
        "knn": knn_p,
        "sequence": sequence_p,
        "body": body_probability(closed),
        "close_position": close_position_probability(closed),
        "wick": wick_probability(closed),
        "regime": regime_probability(closed),
    }
    green_probability = sum(components[name] * weight for name, weight in ENSEMBLE_WEIGHTS.items())
    green_probability = clamp(green_probability, 0.05, 0.95)
    direction = "UP" if green_probability >= 0.5 else "DOWN"
    confidence = green_probability if direction == "UP" else 1.0 - green_probability
    agreement = sum(
        1
        for probability in components.values()
        if abs(probability - 0.5) >= 0.01 and ((probability > 0.5) == (direction == "UP"))
    )
    return ColorForecast(
        direction=direction,
        green_probability=green_probability,
        confidence=confidence,
        agreement=agreement,
        components=components,
        sequence_samples=sequence_samples,
        sequence_by_length=by_length,
        knn_samples=knn_samples,
        knn_mean_distance=mean_distance,
    )
