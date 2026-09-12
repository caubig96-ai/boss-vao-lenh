from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime

import runtime_v374 as v374


APP_VERSION = "3.7.5"
SIGNAL_MODE_NORMAL = "NORMAL"
SIGNAL_MODE_INVERSE = "INVERSE"
log = logging.getLogger("boss-vao-lenh-v375")

# Keep inherited visible version text current while preserving frozen release constants.
v374.v373.v372.v371.v37.v361.v36.v357.v356.v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


def opposite_direction(direction: str) -> str:
    return "DOWN" if str(direction).upper() == "UP" else "UP"


def agreement_for_direction(forecast, direction: str) -> int:
    want_up = str(direction).upper() == "UP"
    return sum(
        1
        for probability in forecast.components.values()
        if abs(float(probability) - 0.5) >= 0.01
        and ((float(probability) > 0.5) == want_up)
    )


def invert_forecast(forecast):
    """Contrarian view of the same six analyses, without pretending support flipped.

    The six component probabilities remain untouched. Only the traded direction is
    reversed, so agreement is recomputed for the opposite side. Therefore a normal
    4/6 bullish setup becomes at most a 2/6 bearish setup (neutral sources excluded),
    which naturally turns MUA NGAY into KHÔNG NÊN VÀO when history/support is weak.
    """
    direction = opposite_direction(forecast.direction)
    agreement = agreement_for_direction(forecast, direction)
    confidence = (
        float(forecast.green_probability)
        if direction == "UP"
        else 1.0 - float(forecast.green_probability)
    )
    return replace(
        forecast,
        direction=direction,
        confidence=max(0.0, min(1.0, confidence)),
        agreement=agreement,
    )


class CompactTelegramBotV375(v374.CompactTelegramBotV374):
    """V3.7.5 keyboard adds a persistent normal/inverse signal toggle."""

    def __init__(self, token: str, chat_id: str, handler, offset_saver=None):
        super().__init__(token, chat_id, handler, offset_saver)
        self.inverse_enabled = False

    def keyboard(self, enabled: bool | None = None) -> dict:
        base = super().keyboard(enabled)
        rows = list(base.get("inline_keyboard", []))
        toggle = {
            "text": (
                "🔁 ĐẢO TÍN HIỆU: BẬT"
                if self.inverse_enabled
                else "↔️ ĐẢO TÍN HIỆU: TẮT"
            ),
            "callback_data": "toggle_inverse_signal",
        }
        # Keep stop/start first, then place the strategy toggle where it is easy to see.
        insert_at = 1 if rows else 0
        rows.insert(insert_at, [toggle])
        return {"inline_keyboard": rows}


class TradingSignalBotV3(v374.TradingSignalBotV3):
    """V3.7.5: one COLOR ENGINE with optional contrarian execution mode."""

    def __init__(self, config):
        super().__init__(config)
        self.telegram = CompactTelegramBotV375(
            config.telegram_token,
            config.telegram_chat_id,
            self.handle_telegram,
            self._save_telegram_offset,
        )

    async def setup(self) -> None:
        await super().setup()
        columns = await (await self.db.conn.execute("PRAGMA table_info(color_predictions)" )).fetchall()
        names = {str(row[1]) for row in columns}
        if "signal_mode" not in names:
            await self.db.conn.execute(
                "ALTER TABLE color_predictions ADD COLUMN signal_mode TEXT NOT NULL DEFAULT 'NORMAL'"
            )
            await self.db.conn.commit()
        self.telegram.inverse_enabled = await self.inverse_signal_enabled()

    async def inverse_signal_enabled(self) -> bool:
        return await self.db.get("inverse_signal_enabled", "0") == "1"

    async def current_signal_mode(self) -> str:
        return SIGNAL_MODE_INVERSE if await self.inverse_signal_enabled() else SIGNAL_MODE_NORMAL

    @staticmethod
    def signal_mode_label(mode: str) -> str:
        return "🔁 ĐẢO TÍN HIỆU" if mode == SIGNAL_MODE_INVERSE else "➡️ TÍN HIỆU THUẬN"

    async def _prediction_signal_mode(self, open_time: int) -> str:
        try:
            row = await (await self.db.conn.execute(
                "SELECT signal_mode FROM color_predictions WHERE market_open_time=?",
                (int(open_time),),
            )).fetchone()
            if row is not None and str(row["signal_mode"]).upper() == SIGNAL_MODE_INVERSE:
                return SIGNAL_MODE_INVERSE
        except Exception:
            pass
        return SIGNAL_MODE_NORMAL

    async def agreement_stats_since_reset(self) -> dict[int, dict[str, int | float]]:
        reset_at = int(await self.db.get("stats_reset_at", "0"))
        mode = await self.current_signal_mode()
        rows = await (await self.db.conn.execute(
            """SELECT agreement,
                      SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
                      SUM(CASE WHEN result='TIE' THEN 1 ELSE 0 END) AS ties
               FROM color_predictions
               WHERE status='SETTLED' AND market_open_time>=?
                 AND agreement BETWEEN 2 AND 6
                 AND COALESCE(signal_mode,'NORMAL')=?
               GROUP BY agreement""",
            (max(0, reset_at), mode),
        )).fetchall()
        result: dict[int, dict[str, int | float]] = {
            level: {"wins": 0, "losses": 0, "ties": 0, "decided": 0, "win_rate": 0.0}
            for level in range(2, 7)
        }
        for row in rows:
            level = int(row["agreement"])
            wins = int(row["wins"] or 0)
            losses = int(row["losses"] or 0)
            ties = int(row["ties"] or 0)
            result[level] = {
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "decided": wins + losses,
                "win_rate": v374._win_rate(wins, losses),
            }
        return result

    async def _color_calibration(self, confidence: float) -> dict:
        label, low, high = v374.v373.v372.v371.v37.color_band(confidence)
        mode = await self.current_signal_mode()
        sql = (
            "SELECT result FROM color_predictions "
            "WHERE status='SETTLED' AND confidence>=? AND COALESCE(signal_mode,'NORMAL')=?"
        )
        params: list[object] = [low, mode]
        if high is not None:
            sql += " AND confidence<?"
            params.append(high)
        sql += " ORDER BY market_open_time DESC LIMIT ?"
        params.append(v374.v373.v372.v371.v37.COLOR_CALIBRATION_MAX_SAMPLES)
        try:
            rows = await (await self.db.conn.execute(sql, tuple(params))).fetchall()
        except Exception:
            rows = []
        wins = sum(1 for row in rows if row["result"] == "WIN")
        losses = sum(1 for row in rows if row["result"] == "LOSS")
        ties = sum(1 for row in rows if row["result"] == "TIE")
        decided = wins + losses
        return {
            "band": label,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "decided": decided,
            "total": decided + ties,
            "win_rate": v374._win_rate(wins, losses),
        }

    async def signal_text(self, p) -> str:
        text = await super().signal_text(p)
        mode = await self._prediction_signal_mode(int(p.market_open_time))
        marker = "━━━━━━━━━━━━━━━━━━━━\n"
        mode_line = f"{self.signal_mode_label(mode)}\n"
        if marker in text:
            return text.replace(marker, marker + mode_line, 1)
        return mode_line + text

    async def threshold_stats_text(self) -> str:
        mode = await self.current_signal_mode()
        text = await super().threshold_stats_text()
        return (
            f"{self.signal_mode_label(mode)}\n"
            + text
            + "\n<i>Thống kê 2/6–6/6 được tách riêng cho chế độ THUẬN và ĐẢO.</i>"
        )

    async def make_decision(self, open_time: int, delay: float) -> None:
        """Forecast from closed candles; optionally reverse only the executed side."""
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
                raw_forecast = v374.v373.v372.v371.v37.predict_next_color(history)
                inverse_enabled = await self.inverse_signal_enabled()
                signal_mode = SIGNAL_MODE_INVERSE if inverse_enabled else SIGNAL_MODE_NORMAL
                forecast = invert_forecast(raw_forecast) if inverse_enabled else raw_forecast

                threshold, threshold_stats, _exact = await self.agreement_entry_policy()
                recommended = int(forecast.agreement) >= int(threshold)
                await super()._save_color_prediction(open_time, live.close_time, forecast, recommended)
                await self.db.conn.execute(
                    "UPDATE color_predictions SET signal_mode=? WHERE market_open_time=?",
                    (signal_mode, int(open_time)),
                )
                await self.db.conn.commit()

                actual = await self.signals_enabled()
                base_bet = float(await self.db.get("base_bet", str(self.config.base_bet)))
                step = int(await self.db.get("bet_step", "1"))
                bet = min(base_bet * (2 if step == 2 else 1), self.config.max_bet)
                prediction = v374.v373.v372.v371.v37.Prediction(
                    int(open_time), int(live.close_time), float(live.open), float(self.live_price),
                    forecast.direction, forecast.confidence, forecast.green_probability,
                    forecast.green_probability, forecast.sequence_samples + forecast.knn_samples,
                    bet, step, bool(actual),
                )
                created = await self.db.create_signal(prediction)
                self.last_decision_open = open_time
                self.last_decision_state = (
                    f"COLOR {forecast.color} {forecast.confidence * 100:.1f}% • "
                    f"{forecast.agreement}/6 • {signal_mode} • BUY>={threshold}/6"
                )

                row = await self._row_for_signal(open_time)
                row = await self._ensure_primary_message(row)
                await self.db.event("SINGLE_COLOR_DECISION_CREATED", {
                    "open_time": int(open_time),
                    "direction": forecast.direction,
                    "raw_direction": raw_forecast.direction,
                    "signal_mode": signal_mode,
                    "green_probability": forecast.green_probability,
                    "confidence": forecast.confidence,
                    "agreement": forecast.agreement,
                    "entry_threshold": threshold,
                    "threshold_decided": int(threshold_stats["decided"]),
                    "threshold_win_rate": float(threshold_stats["win_rate"]),
                    "history_candles": len(history),
                    "recommended": recommended,
                    "created": created,
                    "actual": bool(actual),
                    "legacy_modes_created": 0,
                })
            except Exception as exc:
                self.last_decision_state = f"LỖI COLOR: {type(exc).__name__}"
                log.exception("V3.7.5 color decision failed for %s", open_time)
                try:
                    await self.db.event("SINGLE_COLOR_DECISION_ERROR", {"open_time": open_time, "error": str(exc)})
                except Exception:
                    pass
            finally:
                self.decision_tasks.pop(open_time, None)

            await self._ensure_action_message(open_time)

    async def handle_telegram(self, kind: str, value: str, update: dict) -> None:
        if kind == "callback" and value == "toggle_inverse_signal":
            enabled = not await self.inverse_signal_enabled()
            await self.db.set("inverse_signal_enabled", "1" if enabled else "0")
            self.telegram.inverse_enabled = enabled
            if enabled:
                await self.telegram.send(
                    "🔁 <b>ĐÃ BẬT ĐẢO TÍN HIỆU</b>\n"
                    "Từ phiên M5 kế tiếp: hướng COLOR ENGINE sẽ được đảo TĂNG↔GIẢM. "
                    "6 cách phân tích KHÔNG bị đảo giả; bot tính lại số nguồn thật sự ủng hộ hướng ngược. "
                    "Nếu hướng thuận đang mạnh, hướng đảo thường có ít nguồn ủng hộ và sẽ báo KHÔNG NÊN VÀO.",
                    enabled=await self.db.get("manual_enabled", "1") == "1",
                )
            else:
                await self.telegram.send(
                    "➡️ <b>ĐÃ TRỞ VỀ TÍN HIỆU THUẬN</b>\n"
                    "Từ phiên M5 kế tiếp bot dùng trực tiếp hướng do COLOR ENGINE dự đoán.",
                    enabled=await self.db.get("manual_enabled", "1") == "1",
                )
            return
        await super().handle_telegram(kind, value, update)

    async def status_text(self) -> str:
        text = await super().status_text()
        mode = await self.current_signal_mode()
        return text + f"\n↔️ Chế độ hướng lệnh: <b>{self.signal_mode_label(mode)}</b>"

    async def safe_startup_message(self) -> None:
        try:
            enabled = await self.db.get("manual_enabled", "1") == "1"
            mode = await self.current_signal_mode()
            self.telegram.inverse_enabled = mode == SIGNAL_MODE_INVERSE
            threshold, _stats, _exact = await self.agreement_entry_policy()
            await self.telegram.send(
                f"🤖 <b>BOT V{APP_VERSION} ĐÃ CHẠY</b>\n"
                "🎨 COLOR ENGINE • 6 cách phân tích nến\n"
                f"↔️ Chế độ: <b>{self.signal_mode_label(mode)}</b>\n"
                f"🎯 Ngưỡng MUA NGAY hiện tại: <b>≥{threshold}/6</b>\n"
                "🔁 Có nút ĐẢO TÍN HIỆU để chuyển THUẬN ↔ ĐẢO cho phiên M5 kế tiếp.",
                enabled=enabled,
            )
        except Exception as exc:
            self.telegram.last_error = str(exc)
            log.warning("Startup Telegram send failed; market engine continues: %s", exc)
