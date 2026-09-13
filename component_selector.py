from __future__ import annotations

WINDOW = 100
MIN_SAMPLES = 30


def summarize(results):
    results = [r for r in list(results)[:WINDOW] if r in ("WIN", "LOSS")]
    wins, losses = results.count("WIN"), results.count("LOSS")
    decided = wins + losses
    return dict(
        wins=wins,
        losses=losses,
        decided=decided,
        last=results[0] if results else None,
        win_rate=wins / decided if decided else 0,
        loss_rate=losses / decided if decided else 0,
    )


def inverse_direction(direction):
    return {"UP": "DOWN", "DOWN": "UP"}.get(direction)


def evaluate_method(direction, confidence, results, min_samples=MIN_SAMPLES):
    """Return selection info without mutating the method's original stats.

    Winning method: keep original direction and require latest raw result LOSS.
    Losing method: invert live sent direction and require latest raw result WIN.
    """
    if direction not in ("UP", "DOWN"):
        return None
    stats = summarize(results)
    if stats["decided"] < min_samples:
        return None
    if stats["wins"] > stats["losses"]:
        if stats["last"] != "LOSS":
            return None
        sent = direction
        inverted = False
        edge = stats["win_rate"]
    elif stats["losses"] > stats["wins"]:
        if stats["last"] != "WIN":
            return None
        sent = inverse_direction(direction)
        inverted = True
        edge = stats["loss_rate"]
    else:
        return None
    return {
        "raw_direction": direction,
        "sent_direction": sent,
        "inverted": inverted,
        "confidence": float(confidence or 0),
        "edge": edge,
        **stats,
    }


def choose_best(candidates):
    eligible = [c for c in candidates if c]
    if not eligible:
        return None
    return max(eligible, key=lambda c: (c["confidence"], c["edge"], c["decided"]))
