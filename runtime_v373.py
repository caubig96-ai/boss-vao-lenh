from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import runtime_v354 as v354
import runtime_v372 as v372


APP_VERSION = "3.7.3"
COLOR_ENTRY_MIN_AGREEMENT = 3
log = logging.getLogger("boss-vao-lenh-v373")

# Keep inherited visible version text current while preserving frozen release constants.
v372.v371.v37.v361.v36.v357.v356.v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


class CompactTelegramBotV373(v354.CompactTelegramBotV354):
    """Signal keyboard without the obsolete mode selector.

    CHI TIẾT is attached whenever runtime marks detail_open_time, so the compact
    entry card no longer depends on the literal text "TÍN HIỆU M5" being present.
    """

    def keyboard(self, enabled: bool | None = None) -> dict:
        base = super().keyboard(enabled)
        rows = []
        for row in base.get("inline_keyboard", []):
            filtered = [button for button in row if button.get("callback_data") != "analysis_mode"]
            if filtered:
                rows.append(filtered)
        return {"inline_keyboard": rows}

    async def send(self, text: str, keyboard: bool = True, enabled: bool | None = None) -> int:
        if enabled is not None:
            self.enabled = enabled

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if self.detail_open_time is not None:
            old_rows = self.keyboard(enabled)["inline_keyboard"]
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": "📋 CHI TIẾT", "callback_data": f"detail_{self.detail_open_time}"}],
                    *old_rows,
                ]
            }
        elif keyboard:
            payload["reply_markup"] = self.keyboard(enabled)

        result = await self._call("sendMessage", payload)
        return int(result["message_id"])


def recommend_from_agreement(forecast) -> bool:
    """User rule: from 3/6 agreeing candle analyses, the bot may recommend entry."""
    return int(getattr(forecast, "agreement", 0)) >= COLOR_ENTRY_MIN_AGREEMENT


class TradingSignalBotV3(v372.TradingSignalBotV3):
    """V3.7.3: one COLOR ENGINE, clearer card, and duplicate-safe primary send."""

    def __init__(self, config):
        super().__init__(config)
        self.telegram = CompactTelegramBotV373(
            config.telegram_token,
            config.telegram_chat_id,
            self.handle_telegram,
            self._save_telegram_offset,
        )

    async def setup(self) -> None:
        await super().setup()
        # A previous process can only leave "sending" behind after crashing. The
        # Windows app is single-instance, so it is safe to release stale claims here.
        await self.db.conn.execute(
            "DELETE FROM settings WHERE key LIKE 'signal_message_claim:%' AND value='sending'"
        )
        await self.db.conn.commit()

    async def _claim_signal_message(self, open_time: int) -> bool:
        key = f"signal_message_claim:{open_time}"
        cursor = await self.db.conn.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
            (key, "sending"),
        )
        await self.db.conn.commit()
        return cursor.rowcount == 1

    async def _mark_signal_sent(self, open_time: int) -> None:
        await self.db.set(f"signal_message_claim:{open_time}", "sent")

    async def _release_signal_claim(self, open_time: int) -> None:
        await self.db.conn.execute(
            "DELETE FROM settings WHERE key=? AND value='sending'",
            (f"signal_message_claim:{open_time}",),
        )
        await self.db.conn.commit()

    async def _ensure_primary_message(self, row):
        if row is None or not bool(row["actual"]):
            return row
        open_time = int(row["market_open_time"])
        if row["telegram_message_id"] is not None:
            return row
        if not await self._claim_signal_message(open_time):
            # Another sender owns the same M5. Give it a short chance to persist
            # Telegram message_id, then continue without creating a duplicate.
            for _ in range(20):
                await asyncio.sleep(0.1)
                latest = await self._row_for_signal(open_time)
                if latest is not None and latest["telegram_message_id"] is not None:
                    return latest
            return await self._row_for_signal(open_time)

        self.telegram.detail_open_time = open_time
        try:
            prediction = self._prediction_from_row(row)
            message_id = await self.telegram.send(await self.signal_text(prediction), enabled=True)
            await self.db.update_message_id(open_time, message_id)
            await self._mark_signal_sent(open_time)
            await self.db.event("PRIMARY_SIGNAL_SENT_ONCE", {"open_time": open_time, "message_id": message_id})
        except Exception as exc:
            await self._release_signal_claim(open_time)
            await self.db.event("SIGNAL_SEND_ERROR", {"open_time": open_time, "error": str(exc)})
            self.telegram.last_error = str(exc)
        finally:
            self.telegram.detail_open_time = None
        return await self._row_for_signal(open_time)

    async def _ensure_action_message(self, open_time: int) -> None:
        row = await self._row_for_signal(open_time)
        if row is None or row["telegram_message_id"] is None:
            return
        if await self.db.get(f"action_message_sent:{open_time}", "0") == "1":
            return
        if not await self._claim_action_message(open_time):
            return
        prediction = self._prediction_from_row(row)
        try:
            await self.telegram.send(await self._action_message(prediction), keyboard=False)
            await self._mark_action_sent(open_time)
        except Exception as exc:
            await self._release_action_claim(open_time)
            await self.db.event("ACTION_MESSAGE_SEND_ERROR", {"open_time": open_time, "error": str(exc)})

    async def _previous_candle_label(self, open_time: int) -> tuple[str, str]:
        row = await (await self.db.conn.execute(
            """SELECT open,close FROM candles
               WHERE interval='5m' AND open_time<?
               ORDER BY open_time DESC LIMIT 1""",
            (int(open_time),),
        )).fetchone()
        if row is None:
            return "⚪", "CHƯA CÓ"
        open_price = float(row["open"])
        close_price = float(row["close"])
        if close_price > open_price:
            return "🟢", "XANH"
        if close_price < open_price:
            return "🔴", "ĐỎ"
        return "⚪", "DOJI"

    async def signal_text(self, p) -> str:
        stats, _qualified = await self._signal_calibration(p)
        pairs = await self.pair_stats_since_reset()
        totals = await self._entry_totals_since_reset()
        color_row = await self._color_prediction_row(int(p.market_open_time))
        agreement = int(color_row["agreement"]) if color_row is not None else 0
        previous_icon, previous_color = await self._previous_candle_label(int(p.market_open_time))

        local_open = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp((p.market_close_time + 1) / 1000, self.config.timezone)
        direction = "MUA TĂNG" if p.direction == "UP" else "MUA GIẢM"
        direction_icon = "🟢" if p.direction == "UP" else "🔴"
        if int(stats.get("decided", 0)) > 0:
            expected = float(stats.get("win_rate", 0.0))
        else:
            expected = float(p.confidence) * 100.0

        return (
            f"{direction_icon} <b>{direction}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {local_open:%H:%M}–{local_close:%H:%M}\n"
            f"📊 Dự kiến thắng: <b>{expected:.1f}%</b>\n"
            f"📋 Tổng: ✅ {totals['wins']} thắng • ❌ {totals['losses']} thua\n"
            f"🔗 Cặp: ✅ {pairs['win_pairs']} thắng • ❌ {pairs['loss_pairs']} thua\n"
            f"💵 Giá: <code>{p.signal_price:,.2f}</code> • <b>LỆNH {p.bet_step}</b>: {p.bet_amount:.2f} USDT\n"
            f"🧩 Phân tích cùng hướng: <b>{agreement}/6</b>\n"
            f"🕯 Nến trước: {previous_icon} <b>{previous_color}</b>"
        )

    async def threshold_stats_text(self) -> str:
        lines = [
            f"📈 <b>HIỆU CHỈNH DỰ ĐOÁN MÀU NẾN V{APP_VERSION}</b>",
            "XANH = Close > Open • ĐỎ = Close < Open • DOJI = hòa",
        ]
        for label, low, high in v372.v371.v37.COLOR_BANDS:
            midpoint = low if high is None else (low + high) / 2.0
            stats = await self._color_calibration(midpoint)
            if int(stats["decided"]) > 0:
                value = f"{stats['win_rate']:.1f}% ({stats['wins']}T/{stats['losses']}B)"
            else:
                value = "chưa có kết quả"
            lines.append(f"• Score {label}%: <b>{value}</b>")
        lines.append(
            f"MUA NGAY: khi ít nhất <b>{COLOR_ENTRY_MIN_AGREEMENT}/6</b> cách phân tích nến cùng hướng với dự đoán tổng hợp."
        )
        return "\n".join(lines)

    async def make_decision(self, open_time: int, delay: float) -> None:
        """Create one color forecast; 3/6 agreeing components are enough to recommend."""
        async with self._decision_send_lock:
            await asyncio.sleep(delay)
            try:
                live = self.live_m5
                if live is None or live.open_time != open_time:
                    try:
                        await self.rest_snapshot()
                    except Exception:
                        pass
                    live = self.live_m5
                if live is None or live.open_time != open_time:
                    self.last_decision_state = "LỖI: KHÔNG CÓ NẾN M5 LIVE"
                    await self.db.event("COLOR_DECISION_SKIPPED_NO_MARKET", {"open_time": open_time})
                    return
                if self.live_price <= 0:
                    self.live_price = live.close

                history = await self._closed_m5_history(open_time)
                forecast = v372.v371.v37.predict_next_color(history)
                recommended = recommend_from_agreement(forecast)
                await self._save_color_prediction(open_time, live.close_time, forecast, recommended)

                actual = await self.signals_enabled()
                base_bet = float(await self.db.get("base_bet", str(self.config.base_bet)))
                step = int(await self.db.get("bet_step", "1"))
                bet = min(base_bet * (2 if step == 2 else 1), self.config.max_bet)
                prediction = v372.v371.v37.Prediction(
                    int(open_time),
                    int(live.close_time),
                    float(live.open),
                    float(self.live_price),
                    forecast.direction,
                    forecast.confidence,
                    forecast.green_probability,
                    forecast.green_probability,
                    forecast.sequence_samples + forecast.knn_samples,
                    bet,
                    step,
                    bool(actual),
                )
                created = await self.db.create_signal(prediction)
                self.last_decision_open = open_time
                self.last_decision_state = (
                    f"COLOR {forecast.color} {forecast.confidence * 100:.1f}% • {forecast.agreement}/6 nguồn"
                )

                row = await self._row_for_signal(open_time)
                row = await self._ensure_primary_message(row)
                await self.db.event("SINGLE_COLOR_DECISION_CREATED", {
                    "open_time": int(open_time),
                    "direction": forecast.direction,
                    "green_probability": forecast.green_probability,
                    "confidence": forecast.confidence,
                    "agreement": forecast.agreement,
                    "entry_min_agreement": COLOR_ENTRY_MIN_AGREEMENT,
                    "history_candles": len(history),
                    "recommended": recommended,
                    "created": created,
                    "actual": bool(actual),
                    "legacy_modes_created": 0,
                })
            except Exception as exc:
                self.last_decision_state = f"LỖI COLOR: {type(exc).__name__}"
                log.exception("V3.7.3 color decision failed for %s", open_time)
                try:
                    await self.db.event("SINGLE_COLOR_DECISION_ERROR", {"open_time": open_time, "error": str(exc)})
                except Exception:
                    pass
            finally:
                self.decision_tasks.pop(open_time, None)

            await self._ensure_action_message(open_time)

    async def retry_unsent_loop(self) -> None:
        """Outbox shares the same atomic primary claim as make_decision."""
        while True:
            try:
                now_ms = self.server_now_ms()
                rows = await (await self.db.conn.execute(
                    """SELECT * FROM signals WHERE actual=1 AND telegram_message_id IS NULL
                       AND market_close_time>? ORDER BY market_open_time LIMIT 5""",
                    (now_ms,),
                )).fetchall()
                for row in rows:
                    latest = await self._ensure_primary_message(row)
                    if latest is not None and latest["telegram_message_id"] is not None:
                        await self._ensure_action_message(int(latest["market_open_time"]))
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("V3.7.3 Telegram outbox recovered an unexpected error")
                await asyncio.sleep(5)

    async def safe_startup_message(self) -> None:
        try:
            enabled = await self.db.get("manual_enabled", "1") == "1"
            await self.telegram.send(
                f"🤖 <b>BOT V{APP_VERSION} ĐÃ CHẠY</b>\n"
                "🎨 Chế độ duy nhất: <b>COLOR ENGINE</b>\n"
                f"🧩 Từ <b>{COLOR_ENTRY_MIN_AGREEMENT}/6</b> cách phân tích cùng hướng có thể báo MUA NGAY.\n"
                "🚫 Đã bỏ nút CHỌN CHẾ ĐỘ.",
                enabled=enabled,
            )
        except Exception as exc:
            self.telegram.last_error = str(exc)
            log.warning("Startup Telegram send failed; market engine continues: %s", exc)
