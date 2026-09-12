"""Selection uses immutable RAW outcomes, never executed trade outcomes."""
from __future__ import annotations

import math

METHODS = ("knn", "sequence", "body", "close_position", "wick", "regime")
WINDOW = 100
MIN_SAMPLES = 30


def raw_direction(probability):
    try:
        value = float(probability)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or not 0 <= value <= 1 or abs(value - .5) < .01:
        return None
    return "UP" if value > .5 else "DOWN"


def summarize(results):
    results = list(results)[:WINDOW]  # newest first, settled predictions only
    wins, losses = results.count("WIN"), results.count("LOSS")
    decided = wins + losses
    return dict(wins=wins, losses=losses, ties=results.count("TIE"),
                decided=decided, last=results[0] if results else None,
                win_rate=wins / decided if decided else 0,
                loss_rate=losses / decided if decided else 0)


def select_method(components, stats, min_samples=MIN_SAMPLES):
    candidates = []
    for index, method in enumerate(METHODS):
        direction = raw_direction(components.get(method))
        s = stats[method]
        if direction is None or s["decided"] < min_samples:
            continue
        inverse = s["losses"] > s["wins"]
        # Filter on the last RAW result; do not rewrite it as an executed win.
        if s["last"] != ("WIN" if inverse else "LOSS"):
            continue
        rate = s["loss_rate"] if inverse else s["win_rate"]
        executed = ("DOWN" if direction == "UP" else "UP") if inverse else direction
        candidate = dict(method=method, raw_direction=direction,
                         direction=executed, inverse=inverse, ranking_rate=rate,
                         raw_stats=dict(s))
        candidates.append((rate, s["decided"], -index, candidate))
    return max(candidates, key=lambda x: x[:3])[3] if candidates else None
