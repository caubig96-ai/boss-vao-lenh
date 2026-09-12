from __future__ import annotations

import asyncio
import logging

import runtime_v37 as v37


APP_VERSION = "3.7.1"
log = logging.getLogger("boss-vao-lenh-v371")

# Keep inherited visible status/version text current.
v37.v361.v36.v357.v356.v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


class TradingSignalBotV3(v37.TradingSignalBotV3):
    """V3.7.1: one and only one decision mode — closed-history candle color.

    The old nine analysis modes are no longer generated, ranked, selectable, or
    written as new mode_signals. Existing historical mode_signals are left in the
    database only for backward compatibility/audit and are ignored by this runtime.
    Every M5 decision uses the V3.7 six-component RED/GREEN color ensemble.
    """

    async def setup(self) -> None:
        await super().setup()
        await self.db.set("auto_mode_enabled", "1")
        await self.db.set("analysis_mode", "AUTO")

    async def auto_mode_enabled(self) -> bool:
        return True

    async def current_analysis_mode(self) -> str:
        return "AUTO"

    async def _signal_calibration(self, p):
        row = await self._color_prediction_row(int(p.market_open_time))
        stats = await self._color_calibration(float(p.confidence))
        recommended = bool(row["recommended"]) if row is not None else False
        visible = dict(stats)
        if int(visible.get("decided", 0)) < v37.COLOR_CALIBRATION_MIN_SAMPLES:
            visible["decided"] = 0
        return visible, recommended

    async def make_decision(self, open_time: int, delay: float) -> None:
        """Create exactly one color forecast and never create the nine legacy modes."""
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
                forecast = v37.predict_next_color(history)
                calibration = await self._color_calibration(forecast.confidence)
                recommended = v37.recommendation_from_forecast(forecast, calibration)
                await self._save_color_prediction(open_time, live.close_time, forecast, recommended)

                actual = await self.signals_enabled()
                base_bet = float(await self.db.get("base_bet", str(self.config.base_bet)))
                step = int(await self.db.get("bet_step", "1"))
                bet = min(base_bet * (2 if step == 2 else 1), self.config.max_bet)
                prediction = v37.Prediction(
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
                    f"COLOR {forecast.color} {forecast.confidence * 100:.1f}% "
                    f"• {forecast.agreement}/6 nguồn"
                )

                row = await self._row_for_signal(open_time)
                if row is not None and bool(row["actual"]) and row["telegram_message_id"] is None:
                    self.telegram.detail_open_time = open_time
                    try:
                        message_id = await self.telegram.send(
                            await self.signal_text(self._prediction_from_row(row)),
                            enabled=True,
                        )
                        await self.db.update_message_id(open_time, message_id)
                    finally:
                        self.telegram.detail_open_time = None

                await self.db.event("SINGLE_COLOR_DECISION_CREATED", {
                    "open_time": int(open_time),
                    "direction": forecast.direction,
                    "green_probability": forecast.green_probability,
                    "confidence": forecast.confidence,
                    "agreement": forecast.agreement,
                    "sequence_samples": forecast.sequence_samples,
                    "knn_samples": forecast.knn_samples,
                    "history_candles": len(history),
                    "recommended": recommended,
                    "created": created,
                    "actual": bool(actual),
                    "legacy_modes_created": 0,
                })
            except Exception as exc:
                self.last_decision_state = f"LỖI COLOR: {type(exc).__name__}"
                log.exception("Single color decision failed for %s", open_time)
                try:
                    await self.db.event("SINGLE_COLOR_DECISION_ERROR", {"open_time": open_time, "error": str(exc)})
                except Exception:
                    pass
            finally:
                self.decision_tasks.pop(open_time, None)

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

    async def detail_signal_text(self, p) -> str:
        return await self._color_detail(p)

    async def status_text(self) -> str:
        text = await v37.v361.v36.v357.TradingSignalBotV3.status_text(self)
        return (
            text
            + f"\n🎨 <b>CHẾ ĐỘ DUY NHẤT • COLOR ENGINE V{APP_VERSION}</b>"
            + "\n🧩 kNN + chuỗi màu + thân + Close + râu + regime"
            + f"\n🗂 Lịch sử tối đa: <b>{v37.COLOR_HISTORY_CANDLES}</b> nến M5 đã đóng"
            + "\n🚫 9 chế độ cũ: <b>ĐÃ TẮT, KHÔNG CÒN TẠO TÍN HIỆU</b>"
        )

    async def _send_auto_mode_menu(self) -> int:
        result = await self.telegram._call("sendMessage", {
            "chat_id": self.telegram.chat_id,
            "text": (
                "🧠 <b>CHẾ ĐỘ PHÂN TÍCH</b>\n\n"
                "✅ <b>COLOR ENGINE - CHẾ ĐỘ DUY NHẤT</b>\n"
                "Dự đoán cây M5 sẽ đóng XANH hay ĐỎ bằng 6 nguồn: kNN mẫu tương tự, "
                "chuỗi màu, lực thân, vị trí Close, râu nến và regime/cấu trúc.\n\n"
                "9 chế độ cũ đã bị loại khỏi quyết định và không còn được chạy nền."
            ),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[{
                "text": "✅ COLOR ENGINE ĐANG BẬT",
                "callback_data": "mode_color_only",
            }]]},
        })
        return int(result["message_id"])

    async def handle_telegram(self, kind: str, value: str, update: dict) -> None:
        if kind == "callback" and value == "analysis_mode":
            await self._send_auto_mode_menu()
            return
        if kind == "callback" and (value == "mode_color_only" or value == "mode_auto_best" or value.startswith("mode_")):
            await self.db.set("auto_mode_enabled", "1")
            await self.db.set("analysis_mode", "AUTO")
            await self.telegram.send(
                "🎨 <b>COLOR ENGINE LÀ CHẾ ĐỘ DUY NHẤT</b>\n9 chế độ cũ đã tắt.",
                keyboard=False,
            )
            return
        if kind == "message":
            command = value.strip().split()[0].lower() if value.strip() else ""
            if command in {"/mode", "/modes"}:
                await self._send_auto_mode_menu()
                return
        await super().handle_telegram(kind, value, update)
