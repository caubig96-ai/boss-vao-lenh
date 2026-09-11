from __future__ import annotations

import time

import runtime_v34 as v34
from models import Candle


APP_VERSION = "3.5.0"

# Synchronize inherited status / Telegram version strings.
v34.APP_VERSION = APP_VERSION
v34.v33.APP_VERSION = APP_VERSION
v34.v33.base_runtime.APP_VERSION = APP_VERSION


class TradingSignalBotV3(v34.TradingSignalBotV3):
    """V3.5: Binance Futures Kline is the only source of candle OHLC.

    aggTrade remains connected only for the fast LAST/PRICE display and health
    diagnostics. It is never allowed to create, stretch, merge, or overwrite an
    M1/M5 candle. Live and closed candles come from Binance kline_1m/kline_5m
    WebSocket payloads, with REST /fapi/v1/klines as the fallback/repair source.

    This keeps the candles used by the chart and by the analysis on the same
    official Binance time buckets and OHLC values.
    """

    candle_source = "BINANCE_FUTURES_KLINE_ONLY"

    async def handle_market_message(self, data: dict) -> None:
        event = data.get("e")
        event_time_ms = int(data.get("E") or self.server_now_ms())
        self.last_market_event_ms = max(self.last_market_event_ms, event_time_ms)

        observed_offset = event_time_ms - int(time.time() * 1000)
        if abs(observed_offset - self.server_offset_ms) > 500:
            self.server_offset_ms = observed_offset

        if event == "aggTrade":
            # PRICE ONLY. Do not call _apply_trade_to_live().
            self._mark_rx("trade")
            trade_time_ms = int(data.get("T") or event_time_ms)
            if trade_time_ms < self.last_trade_time_ms:
                return
            self.last_trade_time_ms = trade_time_ms
            self.trade_ticks += 1
            self.live_price = float(data["p"])
            return

        if event != "kline":
            return

        self._mark_rx("kline")
        raw = Candle.from_ws(data)
        attr = "live_m1" if raw.interval == "1m" else "live_m5"
        current: Candle | None = getattr(self, attr)

        # The Binance Kline payload is authoritative. Never merge aggTrade-made
        # highs/lows/closes into it. Reject only an older bucket arriving late.
        if current is None or raw.open_time >= current.open_time:
            setattr(self, attr, raw)

        # Keep aggTrade as the fastest displayed price when it is fresh. If it is
        # unavailable/stale, the official kline close is a safe display fallback.
        trade_age = self._age(self.last_trade_rx_mono)
        if self.live_price <= 0 or trade_age is None or trade_age > 1.0:
            self.live_price = raw.close

        if raw.interval == "5m":
            self.schedule_decision(raw, event_time_ms)

        if raw.closed:
            await self._store_closed(raw)
