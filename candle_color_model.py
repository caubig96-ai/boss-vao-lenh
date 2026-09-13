from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class CandleColorPrediction:
    direction: str
    confidence: float
    reason: str = ""


def candle_direction(open_price: float, close_price: float) -> str:
    """Binary candle direction used by V3.7.9: equal close counts as UP/GREEN."""
    return "UP" if close_price >= open_price else "DOWN"


def settle_prediction(direction: str, open_price: float, close_price: float) -> str:
    actual = candle_direction(open_price, close_price)
    return "WIN" if direction == actual else "LOSS"


def clamp_probability(value: float) -> float:
    try:
        value = float(value)
    except Exception:
        return 0.5
    return max(0.0, min(1.0, value))


def choose_direction(prob_up: float, threshold: float = 0.5) -> CandleColorPrediction:
    p = clamp_probability(prob_up)
    if p >= threshold:
        return CandleColorPrediction("UP", p, "probability")
    return CandleColorPrediction("DOWN", 1.0 - p, "probability")


def recent_accuracy(results: Iterable[str]) -> float:
    values = [r for r in results if r in ("WIN", "LOSS")]
    if not values:
        return 0.0
    return values.count("WIN") / len(values)


def normalize_direction(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip().upper()
    if value in {"UP", "GREEN", "XANH", "CALL", "BUY"}:
        return "UP"
    if value in {"DOWN", "RED", "DO", "ĐỎ", "PUT", "SELL"}:
        return "DOWN"
    return None
