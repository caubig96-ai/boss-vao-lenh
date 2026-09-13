from __future__ import annotations

from statistics import mean


def sma(values, period):
    values = list(values)
    if period <= 0 or len(values) < period:
        return None
    return mean(values[-period:])


def ema(values, period):
    values = list(values)
    if period <= 0 or not values:
        return None
    k = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = value * k + result * (1 - k)
    return result


def rsi(values, period=14):
    values = list(values)
    if len(values) <= period:
        return None
    gains, losses = [], []
    for a, b in zip(values[-period-1:-1], values[-period:]):
        diff = b - a
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def candle_body(open_price, close_price):
    return abs(close_price - open_price)


def candle_range(high, low):
    return max(0.0, high - low)
