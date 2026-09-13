from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import datetime

import runtime_v375 as v375


APP_VERSION = "3.7.6"
INVERSE_MAX_RAW_AGREEMENT = 3
INVERSE_MIN_EXECUTED_SUPPORT = 3
log = logging.getLogger("boss-vao-lenh-v376")

v375.v374.v373.v372.v371.v37.v361.v36.v357.v356.v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


def inverse_entry_allowed(raw_agreement: int, executed_agreement: int) -> bool:
    """In inverse mode, 4/6+ support for the original side is explicitly NO BUY."""
    return (
        int(raw_agreement) <= INVERSE_MAX_RAW_AGREEMENT
        and int(executed_agreement) >= INVERSE_MIN_EXECUTED_SUPPORT
    )


class TradingSignalBotV3(v375.TradingSignalBotV3):
    """V3.7.6: inverse mode keeps the ORIGINAL X/6 visible and interprets it contrarian."""

    async def _inverse_support_from_row(self, open_time: int, executed_direction: str) -> int:
        row = await self._color_prediction_row(open_time)
        if row is None:
            return 0
        try:
            details = json.loads(row["details_json"] or "{}")
            components = details.get("components", {})
            want_up = executed_direction == "UP"
            return sum(
                1
                for value in components.values()
                if abs(float(value) - 0.5) >= 0.01
                and ((float(value) > 0.5) == want_up)
            )
        except Exception:
            return max(0, 6 - int(row["agreement"] or 0))

    async def signal_text(self, p) -> str:
        mode = await self._prediction_signal_mode(int(p.market_open_time))
        if mode != v375.SIGNAL_MODE_INVERSE:
            return await super().signal_text(p)

        stats, _qualified = await self._signal_calibration(p)
        pairs = await self.pair_stats_since_reset()
        totals = await self._entry_totals_since_reset()
        color_row = await self._color_prediction_row(int(p.market_open_time))
        raw_agreement = int(color_row["agreement"]) if color_row is not None else 0
        inverse_support = await self._inverse_support_from_row(int(p.market_open_time), p.direction)
        previous_icon, previous_color = await self._previous_candle_label(int(p.market_open_time))
        exact = await self.agreement_stats_since_reset()

        local_open = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp((p.market_close_time + 1) / 1000, self.config.timezone)
        direction = "MUA TĂNG" if p.direction == "UP" else "MUA GIẢM"
        direction_icon = "🟢" if p.direction == "UP" else "🔴"
        expected = float(stats.get("win_rate", 0.0)) if int(stats.get("decided", 0)) > 0 else float(p.confidence) * 100.0
        agreement_lines = "\n".join(self._agreement_line(level, exact[level]) for level in range(2, 7))
        allowed = inverse_entry_allowed(raw_agreement, inverse_support)
        verdict = "✅ CÓ THỂ VÀO" if allowed else "⚠️ KHÔNG NÊN VÀO"

        return (
            f"{direction_icon} <b>{direction}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔁 <b>ĐẢO TÍN HIỆU</b>\n"
            f"⏰ {local_open:%H:%M}–{local_close:%H:%M}\n"
            f"📊 Dự kiến thắng: <b>{expected:.1f}%</b>\n"
            f"📋 Tổng: ✅ {totals['wins']} thắng • ❌ {totals['losses']} thua\n"
            f"🔗 Cặp: ✅ {pairs['win_pairs']} thắng • ❌ {pairs['loss_pairs']} thua\n"
            f"💵 Giá: <code>{p.signal_price:,.2f}</code> • <b>LỆNH {p.bet_step}</b>: {p.bet_amount:.2f} USDT\n"
            f"🧩 Đồng thuận gốc: <b>{raw_agreement}/6</b>\n"
            f"🔄 Ủng hộ hướng đảo: <b>{inverse_support}/6</b> • {verdict}\n"
            "📚 <b>Lịch sử chế độ ĐẢO theo đồng thuận gốc:</b>\n"
            f"{agreement_lines}\n"
            f"🎯 Quy tắc ĐẢO: gốc <b>≤{INVERSE_MAX_RAW_AGREEMENT}/6</b> và hướng đảo <b>≥{INVERSE_MIN_EXECUTED_SUPPORT}/6</b> mới MUA NGAY\n"
            f"🕯 Nến trước: {previous_icon} <b>{previous_color}</b>"
        )

    async def threshold_stats_text(self) -> str:
        mode = await self.current_signal_mode()
        if mode != v375.SIGNAL_MODE_INVERSE:
            return await super().threshold_stats_text()
        exact = await self.agreement_stats_since_reset()
        lines = [
            f"🔁 <b>ĐẢO TÍN HIỆU • V{APP_VERSION}</b>",
            "Trong chế độ ĐẢO, X/6 là mức đồng thuận của hướng GỐC.",
            f"MUA NGAY chỉ khi đồng thuận gốc ≤{INVERSE_MAX_RAW_AGREEMENT}/6 và hướng đảo có ≥{INVERSE_MIN_EXECUTED_SUPPORT}/6 nguồn ủng hộ.",
            "",
        ]
        lines.extend(self._agreement_line(level, exact[level]) for level in range(2, 7))
        lines.append("")
        lines.append("Ví dụ: gốc 4/6 → đảo chỉ còn tối đa 2/6 ủng hộ → KHÔNG NÊN VÀO.")
        return "\n".join(lines)

    async def make_decision(self, open_time: int, delay: float) -> None:
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
                    return
                if self.live_price <= 0:
                    self.live_price = live.close

                history = await self._closed_m5_history(open_time)
                raw_forecast = v375.v374.v373.v372.v371.v37.predict_next_color(history)
                inverse_enabled = await self.inverse_signal_enabled()
                signal_mode = v375.SIGNAL_MODE_INVERSE if inverse_enabled else v375.SIGNAL_MODE_NORMAL

                if inverse_enabled:
                    executed = v375.invert_forecast(raw_forecast)
                    recommended = inverse_entry_allowed(raw_forecast.agreement, executed.agreement)
                    # Store the actually traded direction, but preserve ORIGINAL X/6 for display/history.
                    stored_forecast = replace(executed, agreement=int(raw_forecast.agreement))
                else:
                    executed = raw_forecast
                    threshold, _stats, _exact = await v375.v374.TradingSignalBotV3.agreement_entry_policy(self)
                    recommended = int(raw_forecast.agreement) >= int(threshold)
                    stored_forecast = raw_forecast

                await v375.v374.v373.v372.v371.v37.TradingSignalBotV3._save_color_prediction(
                    self, open_time, live.close_time, stored_forecast, recommended
                )
                await self.db.conn.execute(
                    "UPDATE color_predictions SET signal_mode=? WHERE market_open_time=?",
                    (signal_mode, int(open_time)),
                )
                await self.db.conn.commit()

                actual = await self.signals_enabled()
                base_bet = float(await self.db.get("base_bet", str(self.config.base_bet)))
                step = int(await self.db.get("bet_step", "1"))
                bet = min(base_bet * (2 if step == 2 else 1), self.config.max_bet)
                prediction = v375.v374.v373.v372.v371.v37.Prediction(
                    int(open_time), int(live.close_time), float(live.open), float(self.live_price),
                    executed.direction, executed.confidence, executed.green_probability,
                    executed.green_probability, executed.sequence_samples + executed.knn_samples,
                    bet, step, bool(actual),
                )
                created = await self.db.create_signal(prediction)
                self.last_decision_open = open_time
                self.last_decision_state = (
                    f"COLOR {executed.color} {executed.confidence * 100:.1f}% • RAW {raw_forecast.agreement}/6 • "
                    f"EXEC {executed.agreement}/6 • {signal_mode}"
                )
                row = await self._row_for_signal(open_time)
                await self._ensure_primary_message(row)
                await self.db.event("SINGLE_COLOR_DECISION_CREATED", {
                    "open_time": int(open_time),
                    "direction": executed.direction,
                    "raw_direction": raw_forecast.direction,
                    "signal_mode": signal_mode,
                    "raw_agreement": int(raw_forecast.agreement),
                    "executed_agreement": int(executed.agreement),
                    "recommended": bool(recommended),
                    "created": created,
                    "actual": bool(actual),
                })
            except Exception as exc:
                self.last_decision_state = f"LỖI COLOR: {type(exc).__name__}"
                log.exception("V3.7.6 color decision failed for %s", open_time)
                try:
                    await self.db.event("SINGLE_COLOR_DECISION_ERROR", {"open_time": open_time, "error": str(exc)})
                except Exception:
                    pass
            finally:
                self.decision_tasks.pop(open_time, None)
            await self._ensure_action_message(open_time)

    async def status_text(self) -> str:
        text = await super().status_text()
        if await self.inverse_signal_enabled():
            text += f"\n🔁 Quy tắc ĐẢO: gốc ≤{INVERSE_MAX_RAW_AGREEMENT}/6 + hướng đảo ≥{INVERSE_MIN_EXECUTED_SUPPORT}/6"
        return text

    async def safe_startup_message(self) -> None:
        try:
            enabled = await self.db.get("manual_enabled", "1") == "1"
            mode = await self.current_signal_mode()
            self.telegram.inverse_enabled = mode == v375.SIGNAL_MODE_INVERSE
            extra = (
                f"\n🔁 ĐẢO: 4/6, 5/6, 6/6 của hướng gốc = <b>KHÔNG NÊN VÀO</b>."
                if mode == v375.SIGNAL_MODE_INVERSE else ""
            )
            await self.telegram.send(
                f"🤖 <b>BOT V{APP_VERSION} ĐÃ CHẠY</b>\n"
                "🎨 COLOR ENGINE • 6 cách phân tích nến\n"
                f"↔️ Chế độ: <b>{self.signal_mode_label(mode)}</b>{extra}",
                enabled=enabled,
            )
        except Exception as exc:
            self.telegram.last_error = str(exc)
            log.warning("Startup Telegram send failed: %s", exc)
