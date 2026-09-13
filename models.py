from dataclasses import dataclass


@dataclass
class Candle:
    interval: str
    open_time: int
    open: float
    high: float
    low: float
    close: float


@dataclass
class Signal:
    method: str
    raw_direction: str
    sent_direction: str
    confidence: float
    inverted: bool = False
