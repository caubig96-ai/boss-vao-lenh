from __future__ import annotations

import runtime_v352 as v352


APP_VERSION = "3.5.3"

# Keep inherited runtime/status text on the current visible version without
# mutating the frozen V3.5 implementation constant used by its regression tests.
v352.v351.v35.v34.v33.APP_VERSION = APP_VERSION
v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


class CompactTelegramBotV353(v352.CompactTelegramBotV352):
    """V3.5.3 sender: primary entry card + one runtime-controlled action line."""

    @staticmethod
    def instant_followup_text(text: str) -> str | None:
        # Disable the legacy automatic follow-up completely. V3.5.3 sends the
        # second message explicitly after the primary message is persisted, so
        # it can never be another copy of the signal card.
        return None


class TradingSignalBotV3(v352.TradingSignalBotV3):
    """V3.5.3: exactly one signal card, then exactly one short action/advice line."""

    def __init__(self, config):
        super().__init__(config)
        self.telegram = CompactTelegramBotV353(
            config.telegram_token,
            config.telegram_chat_id,
            self.handle_telegram,
            self._save_telegram_offset,
        )

    async def signal_text(self, p) -> str:
        # Primary message contains only the requested signal summary. Advice is
        # intentionally removed here because it belongs exclusively to message 2.
        stats, _qualified = await self._signal_calibration(p)
        pairs = await self.pair_stats_since_reset()
        from datetime import datetime

        local_open = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp((p.market_close_time + 1) / 1000, self.config.timezone)
        direction = "MUA TĂNG" if p.direction == "UP" else "MUA GIẢM"
        direction_icon = "🟢" if p.direction == "UP" else "🔴"

        if int(stats.get("decided", 0)) > 0:
            expected = float(stats.get("win_rate", 0.0))
        else:
            expected = float(p.confidence) * 100.0

        return (
            f"📥 <b>TÍN HIỆU M5</b>\n"
            f"{direction_icon} <b>{direction}</b>\n"
            f"⏰ {local_open:%H:%M}–{local_close:%H:%M}\n"
            f"📊 Dự kiến thắng: <b>{expected:.1f}%</b>\n"
            f"🔗 Cặp: ✅ {pairs['win_pairs']} thắng • ❌ {pairs['loss_pairs']} thua\n"
            f"💵 Giá: <code>{p.signal_price:,.2f}</code> • <b>LỆNH {p.bet_step}</b>: {p.bet_amount:.2f} USDT"
        )

    async def _action_message(self, p) -> str:
        _stats, qualified = await self._signal_calibration(p)
        side = "TĂNG" if p.direction == "UP" else "GIẢM"
        if qualified:
            return f"🚨 <b>MUA {side} NGAY • LỆNH {p.bet_step} • GIÁ {p.signal_price:,.2f}</b>"
        return f"⚠️ <b>KHÔNG NÊN VÀO LỆNH {side} • LỆNH {p.bet_step} • GIÁ {p.signal_price:,.2f}</b>"

    async def make_decision(self, open_time: int, delay: float) -> None:
        await super().make_decision(open_time, delay)

        row = await self._row_for_signal(open_time)
        if row is None or row["telegram_message_id"] is None:
            return

        sent_key = f"action_message_sent:{open_time}"
        if await self.db.get(sent_key, "0") == "1":
            return

        prediction = self._prediction_from_row(row)
        try:
            await self.telegram.send(await self._action_message(prediction), keyboard=False)
            await self.db.set(sent_key, "1")
            await self.db.event(
                "ACTION_MESSAGE_SENT",
                {"open_time": open_time, "direction": prediction.direction, "bet_step": prediction.bet_step},
            )
        except Exception as exc:
            await self.db.event(
                "ACTION_MESSAGE_SEND_ERROR",
                {"open_time": open_time, "error": str(exc)},
            )
