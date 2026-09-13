"""Selection uses immutable RAW outcomes, never executed trade outcomes.

v3.7.9 fix
----------
The previous selector picked whichever of the 6 methods had the best raw
win-rate over the trailing WINDOW, and additionally allowed inverting a
method's direction if it was a net loser historically. That is a classic
data-snooping trap: with 6 methods x 2 orientations = 12 candidates checked
every single session, at least one of them will look "hot" over ~30-100
samples purely from noise, even if none of the 6 methods has any real edge.
The old code also gated on whether the method's *single last* result matched
a fixed pattern, a rule with no statistical justification that made the
system flip between methods on essentially one coin flip.

This version instead requires that a method's demonstrated win-rate clears
the platform's real breakeven threshold (given the payout rate) with a
statistical safety margin, using the lower bound of a Wilson confidence
interval rather than the raw point estimate. The confidence level itself is
tightened (Bonferroni-style) to account for the fact that 12 candidates are
being screened at once, so a method must show a *meaningfully* real edge
before it's ever selected -- not just have gotten lucky recently. The
practical effect is fewer signals, but each one is backed by evidence that
would very likely still look good on a fresh batch of data, not by noise
laundered through 12 chances to look good.
"""
from __future__ import annotations

import math

METHODS = ("knn", "sequence", "body", "close_position", "wick", "regime")
WINDOW = 100
MIN_SAMPLES = 40
DEFAULT_PAYOUT_RATE = 0.80

# 6 methods x 2 orientations (keep / invert) = 12 candidates evaluated every
# session. Bonferroni-correcting a target 10% family-wise error rate across
# 12 comparisons gives a per-comparison one-sided alpha of ~0.0083 (z~2.39).
_CANDIDATES_TESTED = len(METHODS) * 2
_FAMILYWISE_ALPHA = 0.10
CONFIDENCE_Z = 2.39


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
    return dict(wins=wins, losses=losses, decided=decided,
                last=results[0] if results and results[0] in ("WIN", "LOSS") else None,
                win_rate=wins / decided if decided else 0,
                loss_rate=losses / decided if decided else 0)


def breakeven_rate(payout_rate):
    """Minimum win-rate needed to not lose money at this payout rate.

    A win pays `payout_rate` on the stake, a loss forfeits the stake, so
    expected value is non-negative when p*payout_rate >= (1-p), i.e.
    p >= 1 / (1 + payout_rate).
    """
    payout_rate = max(float(payout_rate), 0.0)
    return 1.0 / (1.0 + payout_rate)


def wilson_lower_bound(wins, n, z=CONFIDENCE_Z):
    """Lower bound of the Wilson score confidence interval for a win-rate.

    Unlike the raw win_rate, this shrinks toward 0.5 when n is small, so a
    method can't qualify on a high win-rate alone if that rate is only
    established over a handful of samples.
    """
    if n <= 0:
        return 0.0
    p = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = p + z2 / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n)
    return max(0.0, (center - margin) / denom)


def select_method(components, stats, min_samples=MIN_SAMPLES, payout_rate=DEFAULT_PAYOUT_RATE):
    """Pick the single best-supported method+orientation, or None.

    A candidate (method, orientation) is only eligible when the *lower
    confidence bound* of its demonstrated win-rate clears breakeven for the
    configured payout rate. Raw WIN/LOSS ledgers (`stats`) are never
    mutated -- only the direction executed for the next session may be
    inverted from the method's raw raw_direction.
    """
    threshold = breakeven_rate(payout_rate)
    candidates = []
    for index, method in enumerate(METHODS):
        direction = raw_direction(components.get(method))
        if direction is None:
            continue
        s = stats[method]
        n = s["decided"]
        if n < min_samples:
            continue
        for inverse in (False, True):
            wins = s["losses"] if inverse else s["wins"]
            lower_bound = wilson_lower_bound(wins, n)
            if lower_bound < threshold:
                continue
            executed = ("DOWN" if direction == "UP" else "UP") if inverse else direction
            candidate = dict(method=method, raw_direction=direction, direction=executed,
                             inverse=inverse, ranking_rate=wins / n, lower_bound=lower_bound,
                             raw_stats=dict(s))
            # Rank by lower_bound (strongest evidence first), then sample size,
            # then prefer the non-inverted reading, then method order -- all
            # deterministic tie-breaks, none of them dependent on the single
            # most recent result.
            candidates.append((lower_bound, n, not inverse, -index, candidate))
    return max(candidates, key=lambda item: item[:4])[4] if candidates else None
