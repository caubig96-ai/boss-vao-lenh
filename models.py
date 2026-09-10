from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Candle:
    interval: str
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool = True

    @classmethod
    def from_rest(cls, interval: str, row: list) -> "Candle":
        return cls(interval, int(row[0]), int(row[6]), float(row[1]), float(row[2]),
                   float(row[3]), float(row[4]), float(row[5]), True)

    @classmethod
    def from_ws(cls, payload: dict) -> "Candle":
        k = payload["k"]
        return cls(k["i"], int(k["t"]), int(k["T"]), float(k["o"]),
                   float(k["h"]), float(k["l"]), float(k["c"]),
                   float(k["v"]), bool(k["x"]))


@dataclass(slots=True)
class Prediction:
    market_open_time: int
    market_close_time: int
    target_price: float
    signal_price: float
    direction: str
    confidence: float
    m1_probability: float
    m5_probability: float
    pattern_samples: int
    bet_amount: float
    bet_step: int
    actual: bool

