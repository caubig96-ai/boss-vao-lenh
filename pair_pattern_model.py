"""Two-method M5 pair matcher used by V3.7.9.

Both methods only inspect closed candles from the 24 hours before the live M5.
The matched pair must also have an already-closed successor, so the forecast never
reads the candle it is trying to predict.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass



METHODS = ("color_pair", "shape_pair")
HISTORY_CANDLES = 24 * 60 // 5
STATS_WINDOW = 100


@dataclass(frozen=True, slots=True)
class PairMatch:
    method: str
    raw_direction: str | None
    similarity: float
    matched_open_time: int
    matched_next_open_time: int
    green_count: int = 0
    red_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def candle_direction(candle) -> str:
    """Binary candle color required by the product: equal open/close is green."""
    return "UP" if float(candle.close) >= float(candle.open) else "DOWN"


def wick_type(candle) -> tuple[bool, bool]:
    """Upper/lower wick presence; only float roundoff is treated as absent."""
    o, h, l, c = map(float, (candle.open, candle.high, candle.low, candle.close))
    tolerance = 4 * max(math.ulp(value) for value in (o, h, l, c))
    return h - max(o, c) > tolerance, min(o, c) - l > tolerance


def find_pair_matches(history, before_open_time=None) -> dict[str, PairMatch | None]:
    """Count closed successors of every ordered color/wick and wick-only pair.

    Body and wick lengths do not participate. No live or future candle can vote.
    Historical triples must precede the two input candles and be consecutive M5s.
    """
    closed = [c for c in history if getattr(c, "closed", False) and c.interval == "5m"]
    if not closed:
        return {method: None for method in METHODS}
    if before_open_time is None:
        before_open_time = max(c.open_time for c in closed) + 300_000
    candles = sorted({c.open_time: c for c in closed
                      if before_open_time - 86_400_000 <= c.open_time < before_open_time
                      and c.close_time < before_open_time}.values(), key=lambda c: c.open_time)
    empty = {method: None for method in METHODS}
    if len(candles) < 5 or [c.open_time for c in candles[-2:]] != [before_open_time-600_000, before_open_time-300_000]:
        return empty
    current = candles[-2:]
    colors = tuple(candle_direction(c) for c in current)
    wicks = tuple(wick_type(c) for c in current)
    votes = {method: [] for method in METHODS}
    for i in range(len(candles) - 4):
        a, b, successor = candles[i:i+3]
        if b.open_time-a.open_time != 300_000 or successor.open_time-b.open_time != 300_000:
            continue
        if (wick_type(a), wick_type(b)) != wicks:
            continue
        votes["shape_pair"].append((a, successor))
        if (candle_direction(a), candle_direction(b)) == colors:
            votes["color_pair"].append((a, successor))
    for method, occurrences in votes.items():
        if not occurrences:
            continue
        green = sum(candle_direction(n) == "UP" for _, n in occurrences)
        red = len(occurrences) - green
        direction = "UP" if green > red else "DOWN" if red > green else None
        a, successor = occurrences[-1]
        empty[method] = PairMatch(method, direction, 1.0, int(a.open_time),
                                 int(successor.open_time), green, red)
    return empty


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
    """The exact color + wick majority controls the order; never invert it.

    Wick-only counts remain an informational second method, never a tie fallback.
    """
    match = matches.get("color_pair")
    if match is None or match.raw_direction is None:
        return None
    total = match.green_count + match.red_count
    return {
        "method": "color_pair", "raw_direction": match.raw_direction,
        "direction": match.raw_direction, "inverse": False,
        "effective_rate": max(match.green_count, match.red_count) / total if total else 0.5,
        "match": match.to_dict(), "raw_stats": dict(stats["color_pair"]),
    }
