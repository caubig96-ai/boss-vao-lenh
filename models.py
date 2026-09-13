from __future__ import annotations

from dataclasses import dataclass


INTERVAL_MS = {"1m": 60_000, "5m": 300_000}


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

    @staticmethod
    def bucket_open_time(interval: str, trade_time_ms: int) -> int:
        width = INTERVAL_MS[interval]
        return (int(trade_time_ms) // width) * width

    @classmethod
    def from_trade(cls, interval: str, trade_time_ms: int, price: float) -> "Candle":
        """Khởi tạo nến live từ giao dịch đầu tiên nhìn thấy trong bucket.

        Kline chính thức của Binance sẽ thay/căn chỉnh lại open và volume khi tới.
        """
        open_time = cls.bucket_open_time(interval, trade_time_ms)
        close_time = open_time + INTERVAL_MS[interval] - 1
        value = float(price)
        return cls(interval, open_time, close_time, value, value, value, value, 0.0, False)

    def with_trade(self, price: float) -> "Candle":
        """Trả về snapshot nến mới sau một tick, không mutate object đang được UI đọc."""
        value = float(price)
        return Candle(
            self.interval,
            self.open_time,
            self.close_time,
            self.open,
            max(self.high, value),
            min(self.low, value),
            value,
            self.volume,
            False,
        )


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

