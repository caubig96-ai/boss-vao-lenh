"""Two-method M5 pair matcher used by V3.7.9.

Both methods only inspect closed candles from the 24 hours before the live M5.
The matched pair must also have an already-closed successor, so the forecast never
reads the candle it is trying to predict.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from candle_color_model import candle_shape


METHODS = ("color_pair", "shape_pair")
HISTORY_CANDLES = 24 * 60 // 5
SHAPE_MIN_SIMILARITY = 0.90
STATS_WINDOW = 100


@dataclass(frozen=True, slots=True)
class PairMatch:
    method: str
    raw_direction: str
    similarity: float
    matched_open_time: int
    matched_next_open_time: int

    def to_dict(self) -> dict:
        return asdict(self)


def candle_direction(candle) -> str:
    """Binary candle color required by the product: equal open/close is green."""
    return "UP" if float(candle.close) >= float(candle.open) else "DOWN"


def _shape_vector(candle) -> tuple[float, ...]:
    shape = candle_shape(candle)
    # Every value is normalized to 0..1. Signed body keeps bullish/bearish body
    # orientation while wicks and close position describe the candlestick shape.
    return (
        (shape["signed_body"] + 1.0) / 2.0,
        shape["body_ratio"],
        shape["upper_wick"],
        shape["lower_wick"],
        shape["close_position"],
    )


def pair_shape_similarity(left_pair, right_pair) -> float:
    """Return a bounded 0..1 similarity for two ordered two-candle patterns."""
    left = _shape_vector(left_pair[0]) + _shape_vector(left_pair[1])
    right = _shape_vector(right_pair[0]) + _shape_vector(right_pair[1])
    distance = sum(abs(a - b) for a, b in zip(left, right)) / len(left)
    return max(0.0, min(1.0, 1.0 - distance))


def find_pair_matches(history) -> dict[str, PairMatch | None]:
    """Forecast the next color with one color match and one shape match.

    For exact color ties, the newest historical pair is used. For shapes, only
    the single best pair is used and it must be at least 90% similar.
    """
    candles = [c for c in history if getattr(c, "closed", False)][-HISTORY_CANDLES:]
    if len(candles) < 5:
        return {method: None for method in METHODS}

    current = candles[-2:]
    current_colors = tuple(candle_direction(c) for c in current)
    color_match = None
    shape_match = None
    best_shape = -math.inf

    # i,i+1 is the candidate pair and i+2 is its known next candle. Stop at
    # len-5 so the known successor never overlaps either candle in current.
    for i in range(0, len(candles) - 4):
        pair = candles[i:i + 2]
        successor = candles[i + 2]
        if tuple(candle_direction(c) for c in pair) == current_colors:
            color_match = PairMatch(
                "color_pair", candle_direction(successor), 1.0,
                int(pair[0].open_time), int(successor.open_time),
            )

        similarity = pair_shape_similarity(current, pair)
        # Equal scores prefer the newer occurrence.
        if similarity >= best_shape:
            best_shape = similarity
            shape_match = PairMatch(
                "shape_pair", candle_direction(successor), similarity,
                int(pair[0].open_time), int(successor.open_time),
            )

    if shape_match is not None and shape_match.similarity < SHAPE_MIN_SIMILARITY:
        shape_match = None
    return {"color_pair": color_match, "shape_pair": shape_match}


def summarize(results) -> dict:
    settled = [value for value in list(results)[:STATS_WINDOW] if value in ("WIN", "LOSS")]
    wins = settled.count("WIN")
    losses = settled.count("LOSS")
    decided = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "decided": decided,
        "win_rate": wins / decided if decided else 0.5,
        "loss_rate": losses / decided if decided else 0.5,
    }


def select_method(matches: dict[str, PairMatch | None], stats: dict[str, dict]) -> dict | None:
    """Choose the historically stronger normal or inverted method.

    Raw method results are immutable. A loss-heavy method only reverses the sent
    direction; its raw LOSS history remains LOSS for future comparisons.
    """
    candidates = []
    for index, method in enumerate(METHODS):
        match = matches.get(method)
        if match is None:
            continue
        summary = stats[method]
        inverse = summary["losses"] > summary["wins"]
        effective_rate = summary["loss_rate"] if inverse else summary["win_rate"]
        direction = match.raw_direction
        if inverse:
            direction = "DOWN" if direction == "UP" else "UP"
        selected = {
            "method": method,
            "raw_direction": match.raw_direction,
            "direction": direction,
            "inverse": inverse,
            "effective_rate": effective_rate,
            "match": match.to_dict(),
            "raw_stats": dict(summary),
        }
        candidates.append((effective_rate, summary["decided"], match.similarity, -index, selected))
    return max(candidates, key=lambda item: item[:4])[4] if candidates else None
