from __future__ import annotations

from datetime import datetime

import runtime_v351 as v351


APP_VERSION = "3.5.2"

# Keep inherited runtime/status text on the current visible version without
# changing runtime_v35.APP_VERSION (its regression tests intentionally freeze it).
v351.v35.v34.v33.APP_VERSION = APP_VERSION
v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


class CompactTelegramBotV352(v351.v35.v34.v33.CalibratedTelegramBotV3):
    """Telegram sender for short entry cards with one on-demand detail button."""

    def __init__(self, token: str, chat_id: str, handler, offset_saver=None):
        super().__init__(token, chat_id, handler, offset_saver)
        self.detail_open_time: int | None = None

    @staticmethod
    def instant_followup_text(text: str) -> str | None:
        # Only a setup explicitly marked NÊN VÀO LỆNH gets the second urgent alert.
        if "✅ <b>NÊN VÀO LỆNH</b>" not in text:
            return None
        if "MUA TĂNG" in text:
            return "🚨 <b>MUA TĂNG NGAY</b>"
        if "MUA GIẢM" in text:
            return "🚨 <b>MUA GIẢM NGAY</b>"
        return None

    async def send(self, text: str, keyboard: bool = True, enabled: bool | None = None) -> int:
        if enabled is not None:
            self.enabled = enabled

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        # Entry cards stay compact: only one CHI TIẾT button is shown. Normal
        # status/menu messages keep the existing global control keyboard.
        if self.detail_open_time is not None and "TÍN HIỆU M5" in text:
            payload["reply_markup"] = {
                "inline_keyboard": [[{
                    "text": "📋 CHI TIẾT",
                    "callback_data": f"detail_{self.detail_open_time}",
                }]]
            }
        elif keyboard:
            payload["reply_markup"] = self.keyboard(enabled)

        result = await self._call("sendMessage", payload)
        message_id = int(result["message_id"])

        followup = self.instant_followup_text(text)
        if followup:
            await self._send_instant_followup(followup)
        return message_id


class TradingSignalBotV3(v351.TradingSignalBotV3):
    """V3.5.2: compact Telegram entry/result messages; full analysis on demand."""

    def __init__(self, config):
        super().__init__(config)
        self.telegram = CompactTelegramBotV352(
            config.telegram_token,
            config.telegram_chat_id,
            self.handle_telegram,
            self._save_telegram_offset,
        )

    async def make_decision(self, open_time: int, delay: float) -> None:
        # Parent V3.5.1 still decides whether a setup is recommended and still
        # always sends the selected M5 signal while normal sending is enabled.
        self.telegram.detail_open_time = open_time
        try:
            await super().make_decision(open_time, delay)
        finally:
            self.telegram.detail_open_time = None

    async def _signal_calibration(self, p):
        mode = await self.current_analysis_mode()
        stats = await v351.v35.v34.v33.calibration_stats(self.db, mode, p.confidence)
        _, _, qualified = v351.v35.v34.v33.calibration_quality(stats)
        return stats, qualified

    async def signal_text(self, p) -> str:
        stats, qualified = await self._signal_calibration(p)
        pairs = await self.pair_stats_since_reset()
        local_open = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        # Binance close_time is the final millisecond inside the candle, so using
        # it directly formats 20:19 for a 20:15–20:20 candle. Show the exact next
        # five-minute boundary instead.
        local_close = datetime.fromtimestamp((p.market_open_time + 300_000) / 1000, self.config.timezone)

        direction = "MUA TĂNG" if p.direction == "UP" else "MUA GIẢM"
        direction_icon = "🟢" if p.direction == "UP" else "🔴"
        advice = "✅ <b>NÊN VÀO LỆNH</b>" if qualified else "⚠️ <b>KHÔNG NÊN VÀO LỆNH</b>"

        # Prefer empirical same-mode/same-score-band win rate. Before any result
        # exists in that band, show the model score as the temporary estimate.
        if int(stats.get("decided", 0)) > 0:
            expected = float(stats.get("win_rate", 0.0))
        else:
            expected = float(p.confidence) * 100.0

        return (
            f"📥 <b>TÍN HIỆU M5</b>\n"
            f"{direction_icon} <b>{direction}</b>\n"
            f"{advice}\n"
            f"⏰ {local_open:%H:%M}–{local_close:%H:%M}\n"
            f"📊 Dự kiến thắng: <b>{expected:.1f}%</b>\n"
            f"🔗 Cặp: ✅ {pairs['win_pairs']} thắng • ❌ {pairs['loss_pairs']} thua\n"
            f"💵 Giá: <code>{p.signal_price:,.2f}</code> • <b>LỆNH {p.bet_step}</b>: {p.bet_amount:.2f} USDT"
        )

    async def detail_signal_text(self, p) -> str:
        text = await super().signal_text(p)
        # Parent V3.5.1 is intentionally preserved; only normalize the visible
        # version in the expanded detail card.
        return text.replace("V3.5.1", f"V{APP_VERSION}")

    async def handle_telegram(self, kind: str, value: str, update: dict) -> None:
        if kind == "callback" and value.startswith("detail_"):
            try:
                open_time = int(value.split("_", 1)[1])
            except (TypeError, ValueError):
                await self.telegram.send("Không đọc được mã chi tiết.", keyboard=False)
                return
            row = await self._row_for_signal(open_time)
            if row is None:
                await self.telegram.send("Không còn dữ liệu chi tiết của lệnh này.", keyboard=False)
                return
            prediction = self._prediction_from_row(row)
            await self.telegram.send(await self.detail_signal_text(prediction), keyboard=False)
            return
        await super().handle_telegram(kind, value, update)

    async def result_text(
        self,
        row,
        close_price: float,
        result: str,
        pnl: float,
        open_price: float | None = None,
    ) -> str:
        direction = "TĂNG" if row["direction"] == "UP" else "GIẢM"
        step = int(row["bet_step"])
        if result == "WIN":
            return f"✅ <b>THẮNG {direction} • LỆNH {step}</b>"
        if result == "LOSS":
            return f"❌ <b>THUA {direction} • LỆNH {step}</b>"
        return f"➖ <b>HÒA {direction} • LỆNH {step}</b>"
