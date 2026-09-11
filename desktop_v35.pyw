from __future__ import annotations

from datetime import datetime

import tkinter as tk

import desktop_v3 as desktop
from runtime_v35 import APP_VERSION, TradingSignalBotV3


# Inject V3.5 before BackgroundBot starts.
desktop.APP_VERSION = APP_VERSION
desktop.TradingSignalBotV3 = TradingSignalBotV3


class BinanceKlineTrayApplication(desktop.TrayApplication):
    """Desktop chart that displays only Binance Kline candles on exact time slots."""

    @staticmethod
    def _with_live(closed, live):
        # Deduplicate by Binance open_time and keep chronological order. This
        # prevents the same candle being drawn twice when a close and the live
        # snapshot overlap during a WebSocket/REST handoff.
        by_time = {c.open_time: c for c in list(closed)[-160:]}
        if live is not None:
            by_time[live.open_time] = live
        return [by_time[key] for key in sorted(by_time)][-120:]

    def _check_engine(self) -> None:
        bot = self.engine.bot
        if self.engine.error:
            self.health_var.set(f"V{APP_VERSION} • ENGINE STOPPED • {self.engine.error}")
        elif bot and self.engine.thread and self.engine.thread.is_alive():
            kline_age = bot._age(bot.last_kline_rx_mono)
            rest_age = bot._age(bot.last_rest_ok_mono)
            if kline_age is not None and kline_age <= 2.5:
                source = "BINANCE WS KLINE"
            elif rest_age is not None and rest_age <= 3.5:
                source = "BINANCE REST KLINE"
            else:
                source = "NO KLINE DATA"
            self.health_var.set(f"V{APP_VERSION} • {source} • decision: {bot.last_decision_state}")
            self.price_var.set(f"PRICE {bot.live_price:,.2f}")
            self.tick_var.set(f"PRICE TICKS {bot.trade_ticks:,}")
        elif self.config.telegram_token and self.config.telegram_chat_id:
            self.health_var.set(f"V{APP_VERSION} • engine chưa sẵn sàng")
        self.root.after(500, self._check_engine)

    def show_dashboard(self) -> None:
        super().show_dashboard()
        if not self.dashboard or not self.dashboard.winfo_exists():
            return

        symbol = self.config.symbol

        def relabel(widget):
            for child in widget.winfo_children():
                try:
                    text = str(child.cget("text"))
                    if "M1 – LIVE TỪNG TICK" in text:
                        child.configure(text=f"{symbol} M1 – BINANCE KLINE")
                    elif "M5 – LIVE TỪNG TICK" in text:
                        child.configure(text=f"{symbol} M5 – BINANCE KLINE")
                except Exception:
                    pass
                relabel(child)

        relabel(self.dashboard)

    def _write_diagnostics(self, bot: TradingSignalBotV3) -> None:
        if not self.analysis_text:
            return
        trade_age = bot._age(bot.last_trade_rx_mono)
        kline_age = bot._age(bot.last_kline_rx_mono)
        rest_age = bot._age(bot.last_rest_ok_mono)
        live1 = bot.live_m1
        live5 = bot.live_m5
        text = (
            f"VERSION: {APP_VERSION}\n"
            f"DATABASE: {bot.database_path}\n\n"
            "CANDLE SOURCE: BINANCE FUTURES KLINE ONLY\n"
            "AGGTRADE ROLE: PRICE DISPLAY ONLY - KHÔNG TẠO/SỬA NẾN\n\n"
            f"PRICE: {bot.live_price:,.2f}\n"
            f"PRICE TICKS: {bot.trade_ticks:,}\n"
            f"TRADE AGE: {trade_age if trade_age is not None else -1:.3f}s\n"
            f"KLINE AGE: {kline_age if kline_age is not None else -1:.3f}s\n"
            f"REST AGE: {rest_age if rest_age is not None else -1:.3f}s\n"
            f"WS CONNECTED: {bot.ws_connected}\n"
            f"WS RECONNECTS: {bot.ws_reconnects}\n"
            f"REST FALLBACK HITS: {bot.rest_fallback_hits}\n"
            f"LAST MARKET ERROR: {bot.last_market_error or '-'}\n"
            f"TELEGRAM ERROR: {bot.telegram.last_error or '-'}\n"
            f"TELEGRAM POLL CONFLICT: {bot.telegram.poll_conflict}\n\n"
            f"M1 HISTORY: {len(bot.m1)}/1440\n"
            f"M5 HISTORY: {len(bot.m5)}/288\n"
            f"M1 KLINE LIVE: {self._candle_line(live1)}\n"
            f"M5 KLINE LIVE: {self._candle_line(live5)}\n\n"
            f"LAST DECISION: {bot.last_decision_state}\n"
        )
        self.analysis_text.configure(state="normal")
        self.analysis_text.delete("1.0", tk.END)
        self.analysis_text.insert("1.0", text)
        self.analysis_text.configure(state="disabled")

    def _draw_candles(self, canvas, rows: list, interval: str, bot: TradingSignalBotV3) -> None:
        if not canvas or not canvas.winfo_exists():
            return
        canvas.delete("all")
        width = max(canvas.winfo_width(), 500)
        height = max(canvas.winfo_height(), 280)
        left, right, top, bottom = 60, 95, 68, 34
        plot_w, plot_h = width - left - right, height - top - bottom

        if not rows:
            canvas.create_text(
                width / 2,
                height / 2,
                text="Đang chờ Binance Futures Kline...",
                fill="#b7bdc6",
            )
            return

        interval_ms = 60_000 if interval == "M1" else 300_000
        rows = sorted({c.open_time: c for c in rows}.values(), key=lambda c: c.open_time)

        # Fixed timestamp slots: a missing Binance bucket leaves a visible gap
        # instead of squeezing the remaining candles together or drawing two
        # candles on the same position.
        slots = 80
        last_open = rows[-1].open_time
        start_open = last_open - (slots - 1) * interval_ms
        visible = [c for c in rows if start_open <= c.open_time <= last_open]
        if not visible:
            return

        highs = [float(c.high) for c in visible]
        lows = [float(c.low) for c in visible]
        hi, lo = max(highs), min(lows)
        padding = max((hi - lo) * 0.08, max(abs(hi), 1.0) * 0.00002)
        hi += padding
        lo -= padding
        span = max(hi - lo, 0.01)
        slot_w = plot_w / slots
        body_w = max(2.0, min(9.0, slot_w * 0.62))

        def y(price: float) -> float:
            return top + (hi - price) / span * plot_h

        def x(open_time: int) -> float:
            index = (open_time - start_open) / interval_ms
            return left + (index + 0.5) * slot_w

        kline_age = bot._age(bot.last_kline_rx_mono)
        rest_age = bot._age(bot.last_rest_ok_mono)
        if kline_age is not None and kline_age <= 2.5:
            source = "BINANCE WS KLINE"
        elif rest_age is not None and rest_age <= 3.5:
            source = "BINANCE REST KLINE"
        else:
            source = "KLINE STALE"

        last = visible[-1]
        last_close = float(last.close)
        canvas.create_text(
            left,
            18,
            text=f"{interval} • {source} • KLINE CLOSE {last_close:,.2f}",
            anchor="w",
            fill="#f0b90b",
            font=("Segoe UI", 10, "bold"),
        )
        canvas.create_text(
            left,
            40,
            text="OHLC lấy trực tiếp từ Binance Futures Kline; aggTrade chỉ cập nhật PRICE phía trên",
            anchor="w",
            fill="#848e9c",
            font=("Segoe UI", 8),
        )

        for i in range(6):
            gy = top + plot_h * i / 5
            price = hi - span * i / 5
            canvas.create_line(left, gy, width - right, gy, fill="#202630")
            canvas.create_text(width - right + 5, gy, text=f"{price:,.2f}", anchor="w", fill="#848e9c")

        # Time grid every 10 exact Binance buckets.
        for index in range(0, slots, 10):
            gx = left + (index + 0.5) * slot_w
            open_ms = start_open + index * interval_ms
            label = datetime.fromtimestamp(open_ms / 1000).strftime("%H:%M")
            canvas.create_line(gx, top, gx, top + plot_h, fill="#151a21")
            canvas.create_text(gx, top + plot_h + 15, text=label, fill="#848e9c", font=("Segoe UI", 8))

        for candle in visible:
            cx = x(candle.open_time)
            color = "#0ecb81" if candle.close >= candle.open else "#f6465d"
            canvas.create_line(cx, y(candle.high), cx, y(candle.low), fill=color)
            y_open = y(candle.open)
            y_close = y(candle.close)
            if abs(y_open - y_close) < 1:
                canvas.create_line(cx - body_w / 2, y_open, cx + body_w / 2, y_open, fill=color, width=2)
            else:
                canvas.create_rectangle(
                    cx - body_w / 2,
                    min(y_open, y_close),
                    cx + body_w / 2,
                    max(y_open, y_close),
                    fill=color,
                    outline=color,
                )

        last_y = y(last_close)
        canvas.create_line(left, last_y, width - right, last_y, fill="#f0b90b", dash=(5, 4))
        canvas.create_text(width - right + 5, last_y, text=f"{last_close:,.2f}", anchor="w", fill="#f0b90b")


if __name__ == "__main__":
    desktop.shutdown_legacy_v2()
    _mutex = desktop.acquire_single_instance()
    BinanceKlineTrayApplication().run()
