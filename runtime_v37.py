from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone

import runtime_v361 as v361
from candle_color_model import ColorForecast, predict_next_color
from indicators import all_mode_predictions, analysis_mode_label
from models import Candle, Prediction


APP_VERSION = "3.7.0"
COLOR_HISTORY_CANDLES = max(288, int(os.getenv("COLOR_HISTORY_CANDLES", "8640")))  # 30 days of M5
COLOR_CALIBRATION_MIN_SAMPLES = max(10, int(os.getenv("COLOR_CALIBRATION_MIN_SAMPLES", "30")))
COLOR_CALIBRATION_MAX_SAMPLES = max(
    COLOR_CALIBRATION_MIN_SAMPLES,
    int(os.getenv("COLOR_CALIBRATION_MAX_SAMPLES", "500")),
)
COLOR_RECOMMEND_MIN_CONFIDENCE = float(os.getenv("COLOR_RECOMMEND_MIN_CONFIDENCE", "0.60"))
COLOR_WARMUP_MIN_CONFIDENCE = float(os.getenv("COLOR_WARMUP_MIN_CONFIDENCE", "0.65"))
COLOR_RECOMMEND_MIN_AGREEMENT = max(3, int(os.getenv("COLOR_RECOMMEND_MIN_AGREEMENT", "5")))
COLOR_RECOMMEND_MIN_KNN = max(10, int(os.getenv("COLOR_RECOMMEND_MIN_KNN", "30")))
COLOR_RECOMMEND_MIN_SEQUENCE = max(5, int(os.getenv("COLOR_RECOMMEND_MIN_SEQUENCE", "12")))
COLOR_RECOMMEND_MIN_CALIBRATED_WR = float(os.getenv("COLOR_RECOMMEND_MIN_CALIBRATED_WR", "55.0"))

log = logging.getLogger("boss-vao-lenh-v37")

# Synchronize inherited visible status/version text while retaining frozen old modules.
v361.v36.v357.v356.v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION

COLOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS color_predictions (
    market_open_time INTEGER PRIMARY KEY,
    market_close_time INTEGER NOT NULL,
    direction TEXT NOT NULL,
    green_probability REAL NOT NULL,
    confidence REAL NOT NULL,
    agreement INTEGER NOT NULL,
    sequence_samples INTEGER NOT NULL,
    knn_samples INTEGER NOT NULL,
    recommended INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'PENDING',
    result TEXT,
    actual_color TEXT,
    created_at TEXT NOT NULL,
    settled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_color_predictions_status_time
ON color_predictions(status, market_open_time);
CREATE INDEX IF NOT EXISTS idx_color_predictions_confidence
ON color_predictions(status, confidence, market_open_time);
"""

COLOR_BANDS: tuple[tuple[str, float, float | None], ...] = (
    ("50.0–54.9", 0.50, 0.55),
    ("55.0–59.9", 0.55, 0.60),
    ("60.0–64.9", 0.60, 0.65),
    ("65.0–69.9", 0.65, 0.70),
    ("70.0–74.9", 0.70, 0.75),
    ("75.0+", 0.75, None),
)


def color_band(confidence: float) -> tuple[str, float, float | None]:
    value = max(0.50, min(0.95, float(confidence)))
    for label, low, high in COLOR_BANDS:
        if value >= low and (high is None or value < high):
            return label, low, high
    return COLOR_BANDS[-1]


def recommendation_from_forecast(forecast: ColorForecast, calibration: dict) -> bool:
    """Separate always-on color prediction from selective MUA NGAY advice."""
    if forecast.confidence < COLOR_RECOMMEND_MIN_CONFIDENCE:
        return False
    if forecast.agreement < COLOR_RECOMMEND_MIN_AGREEMENT:
        return False
    if forecast.knn_samples < COLOR_RECOMMEND_MIN_KNN:
        return False
    if forecast.sequence_samples < COLOR_RECOMMEND_MIN_SEQUENCE:
        return False

    decided = int(calibration.get("decided", 0))
    if decided >= COLOR_CALIBRATION_MIN_SAMPLES:
        return float(calibration.get("win_rate", 0.0)) >= COLOR_RECOMMEND_MIN_CALIBRATED_WR

    # Warm-up path is intentionally stricter until enough out-of-sample signals
    # have settled in the same score band.
    return forecast.confidence >= COLOR_WARMUP_MIN_CONFIDENCE


class TradingSignalBotV3(v361.TradingSignalBotV3):
    """V3.7: predict only the final RED/GREEN color of the current M5 candle.

    AUTO mode uses ONLY official, already-closed Binance Futures M5 candles before
    market_open_time. The first ~10 seconds of the live candle are deliberately NOT
    model inputs. The live candle is used only for its official open/close time and
    the displayed signal price. Six closed-history components are ensembled:
    kNN similar patterns, color sequence transitions, body momentum, close position,
    wick pressure, and market regime/structure.
    """

    async def setup(self) -> None:
        await super().setup()
        await self._ensure_color_schema()
        try:
            await self._backfill_color_history()
        except Exception as exc:
            log.warning("30-day color history backfill failed; existing DB history will be used: %s", exc)
        try:
            await self._settle_color_pending_from_db()
        except Exception as exc:
            log.warning("Color pending recovery failed: %s", exc)

    async def _ensure_color_schema(self) -> None:
        if self.db.conn:
            await self.db.conn.executescript(COLOR_SCHEMA)
            await self.db.conn.commit()

    async def _backfill_color_history(self) -> None:
        if not self.http or not self.db.conn:
            return
        rows = await self._recent_closed_klines("5m", COLOR_HISTORY_CANDLES)
        if not rows:
            return
        values = [
            (
                "5m",
                int(row[0]),
                int(row[6]),
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[5]),
            )
            for row in rows
        ]
        await self.db.conn.executemany(
            """INSERT INTO candles(interval,open_time,close_time,open,high,low,close,volume)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(interval,open_time) DO UPDATE SET
               close_time=excluded.close_time,open=excluded.open,high=excluded.high,
               low=excluded.low,close=excluded.close,volume=excluded.volume""",
            values,
        )
        await self.db.conn.commit()
        await self.db.event("COLOR_HISTORY_READY", {"m5_closed": len(values)})

    async def _closed_m5_history(self, before_open_time: int) -> list[Candle]:
        rows = await (await self.db.conn.execute(
            """SELECT open_time,close_time,open,high,low,close,volume
               FROM candles
               WHERE interval='5m' AND open_time<?
               ORDER BY open_time DESC LIMIT ?""",
            (int(before_open_time), COLOR_HISTORY_CANDLES),
        )).fetchall()
        result = [
            Candle(
                "5m",
                int(row["open_time"]),
                int(row["close_time"]),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
                True,
            )
            for row in reversed(rows)
        ]
        return result

    async def _save_color_prediction(
        self,
        open_time: int,
        close_time: int,
        forecast: ColorForecast,
        recommended: bool,
    ) -> None:
        details = {
            "components": forecast.components,
            "sequence_by_length": forecast.sequence_by_length,
            "knn_mean_distance": forecast.knn_mean_distance if math.isfinite(forecast.knn_mean_distance) else None,
            "history_limit": COLOR_HISTORY_CANDLES,
            "model": "closed_m5_color_ensemble_v1",
        }
        await self.db.conn.execute(
            """INSERT OR IGNORE INTO color_predictions(
               market_open_time,market_close_time,direction,green_probability,confidence,
               agreement,sequence_samples,knn_samples,recommended,details_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(open_time),
                int(close_time),
                forecast.direction,
                float(forecast.green_probability),
                float(forecast.confidence),
                int(forecast.agreement),
                int(forecast.sequence_samples),
                int(forecast.knn_samples),
                int(bool(recommended)),
                json.dumps(details, ensure_ascii=False, separators=(",", ":")),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await self.db.conn.commit()

    async def _color_prediction_row(self, open_time: int):
        try:
            return await (await self.db.conn.execute(
                "SELECT * FROM color_predictions WHERE market_open_time=?",
                (int(open_time),),
            )).fetchone()
        except Exception:
            return None

    async def _color_calibration(self, confidence: float) -> dict:
        label, low, high = color_band(confidence)
        sql = (
            "SELECT result FROM color_predictions "
            "WHERE status='SETTLED' AND confidence>=?"
        )
        params: list[object] = [low]
        if high is not None:
            sql += " AND confidence<?"
            params.append(high)
        sql += " ORDER BY market_open_time DESC LIMIT ?"
        params.append(COLOR_CALIBRATION_MAX_SAMPLES)
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
            "win_rate": (wins / decided * 100.0) if decided else 0.0,
        }

    async def _signal_calibration(self, p):
        if not await self.auto_mode_enabled():
            return await super()._signal_calibration(p)
        row = await self._color_prediction_row(int(p.market_open_time))
        stats = await self._color_calibration(float(p.confidence))
        recommended = bool(row["recommended"]) if row is not None else False
        # Keep the compact card from displaying an unstable observed WR from only
        # a handful of examples. It falls back to raw model confidence until mature.
        visible = dict(stats)
        if int(visible.get("decided", 0)) < COLOR_CALIBRATION_MIN_SAMPLES:
            visible["decided"] = 0
        return visible, recommended

    async def make_decision(self, open_time: int, delay: float) -> None:
        if not await self.auto_mode_enabled():
            return await super().make_decision(open_time, delay)

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

                # Preserve the existing nine raw shadow modes for comparison only.
                raw_modes = all_mode_predictions(list(self.m1), list(self.m5), self.live_price, live.open)
                await self.db.create_mode_signals(open_time, live.close_time, live.open, raw_modes)

                # CRITICAL: model history ends strictly before this live candle.
                history = await self._closed_m5_history(open_time)
                forecast = predict_next_color(history)
                calibration = await self._color_calibration(forecast.confidence)
                recommended = recommendation_from_forecast(forecast, calibration)
                await self._save_color_prediction(open_time, live.close_time, forecast, recommended)

                actual = await self.signals_enabled()
                base_bet = float(await self.db.get("base_bet", str(self.config.base_bet)))
                step = int(await self.db.get("bet_step", "1"))
                bet = min(base_bet * (2 if step == 2 else 1), self.config.max_bet)
                prediction = Prediction(
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

                await self.db.event("COLOR_DECISION_CREATED", {
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
                })
            except Exception as exc:
                self.last_decision_state = f"LỖI COLOR: {type(exc).__name__}"
                log.exception("Color decision failed for %s", open_time)
                try:
                    await self.db.event("COLOR_DECISION_ERROR", {"open_time": open_time, "error": str(exc)})
                except Exception:
                    pass
            finally:
                self.decision_tasks.pop(open_time, None)

            # Exactly one second/action message, retaining the V3.5.5 atomic guard.
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

    async def _settle_color_prediction(self, candle: Candle) -> None:
        if candle.interval != "5m":
            return
        row = await self._color_prediction_row(candle.open_time)
        if row is None or row["status"] != "PENDING":
            return
        if candle.close > candle.open:
            actual_color = "GREEN"
            actual_direction = "UP"
        elif candle.close < candle.open:
            actual_color = "RED"
            actual_direction = "DOWN"
        else:
            actual_color = "DOJI"
            actual_direction = None
        if actual_direction is None:
            result = "TIE"
        else:
            result = "WIN" if row["direction"] == actual_direction else "LOSS"
        await self.db.conn.execute(
            """UPDATE color_predictions
               SET status='SETTLED',result=?,actual_color=?,settled_at=?
               WHERE market_open_time=? AND status='PENDING'""",
            (result, actual_color, datetime.now(timezone.utc).isoformat(), candle.open_time),
        )
        await self.db.conn.commit()

    async def settle_market(self, candle) -> None:
        await super().settle_market(candle)
        try:
            await self._ensure_color_schema()
            await self._settle_color_prediction(candle)
        except Exception:
            log.exception("Could not settle color forecast for %s", getattr(candle, "open_time", "?"))

    async def _settle_color_pending_from_db(self) -> None:
        await self._ensure_color_schema()
        rows = await (await self.db.conn.execute(
            "SELECT market_open_time FROM color_predictions WHERE status='PENDING' ORDER BY market_open_time"
        )).fetchall()
        for row in rows:
            candle = await (await self.db.conn.execute(
                """SELECT open_time,close_time,open,high,low,close,volume FROM candles
                   WHERE interval='5m' AND open_time=?""",
                (int(row["market_open_time"]),),
            )).fetchone()
            if candle is None:
                continue
            obj = Candle(
                "5m", int(candle["open_time"]), int(candle["close_time"]),
                float(candle["open"]), float(candle["high"]), float(candle["low"]),
                float(candle["close"]), float(candle["volume"]), True,
            )
            await self._settle_color_prediction(obj)

    async def settle_pending(self) -> None:
        await super().settle_pending()
        try:
            await self._settle_color_pending_from_db()
        except Exception:
            # During the first ever setup the table may not exist until DB open has
            # completed; setup() calls this recovery once more after schema creation.
            pass

    async def _color_detail(self, p) -> str:
        row = await self._color_prediction_row(int(p.market_open_time))
        if row is None:
            return "Không còn dữ liệu dự đoán màu cho phiên này."
        try:
            details = json.loads(row["details_json"] or "{}")
        except Exception:
            details = {}
        components = details.get("components", {})
        calibration = await self._color_calibration(float(row["confidence"]))

        def pct(name: str) -> str:
            value = float(components.get(name, 0.5)) * 100.0
            return f"{value:.1f}% XANH / {100.0 - value:.1f}% ĐỎ"

        predicted = "XANH" if row["direction"] == "UP" else "ĐỎ"
        calibration_line = (
            f"{calibration['win_rate']:.1f}% ({calibration['wins']}T/{calibration['losses']}B)"
            if int(calibration["decided"]) > 0 else "chưa có mẫu đã chấm"
        )
        return (
            f"📋 <b>CHI TIẾT MÀU NẾN • V{APP_VERSION}</b>\n"
            f"🎯 Dự đoán: <b>{predicted}</b> • score {float(row['confidence']) * 100:.1f}%\n"
            f"✅ Đồng thuận: <b>{int(row['agreement'])}/6</b> nguồn\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🧩 kNN mẫu tương tự: {pct('knn')} • {int(row['knn_samples'])} láng giềng\n"
            f"🔁 Chuỗi màu 2–5 nến: {pct('sequence')} • {int(row['sequence_samples'])} mẫu\n"
            f"🟩 Thân nến có trọng số: {pct('body')}\n"
            f"📍 Vị trí Close: {pct('close_position')}\n"
            f"🪡 Áp lực râu nến: {pct('wick')}\n"
            f"📐 Regime/cấu trúc: {pct('regime')}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Hiệu chỉnh vùng {color_band(float(row['confidence']))[0]}%: <b>{calibration_line}</b>\n"
            f"🧪 Lịch sử tối đa: <b>{COLOR_HISTORY_CANDLES} nến M5 đã đóng</b> (~30 ngày)\n"
            "🔒 Mô hình KHÔNG dùng giá/biên độ của nến M5 live để chọn màu; dữ liệu đầu vào kết thúc trước thời điểm mở nến này.\n"
            + ("🚨 <b>ĐỦ ĐIỀU KIỆN MUA NGAY</b>" if bool(row["recommended"]) else "⚠️ <b>CHƯA ĐỦ ĐỒNG THUẬN ĐỂ MUA NGAY</b>")
        )

    async def detail_signal_text(self, p) -> str:
        if await self.auto_mode_enabled():
            return await self._color_detail(p)
        return await super().detail_signal_text(p)

    async def threshold_stats_text(self) -> str:
        if not await self.auto_mode_enabled():
            return await super().threshold_stats_text()
        lines = [
            "📈 <b>HIỆU CHỈNH DỰ ĐOÁN MÀU NẾN V3.7</b>",
            "XANH = Close > Open • ĐỎ = Close < Open • DOJI = hòa",
        ]
        for label, low, high in COLOR_BANDS:
            midpoint = low if high is None else (low + high) / 2.0
            stats = await self._color_calibration(midpoint)
            if int(stats["decided"]) > 0:
                value = f"{stats['win_rate']:.1f}% ({stats['wins']}T/{stats['losses']}B)"
            else:
                value = "chưa có kết quả"
            lines.append(f"• Score {label}%: <b>{value}</b>")
        lines.append(
            f"MUA NGAY: score ≥{COLOR_RECOMMEND_MIN_CONFIDENCE * 100:.0f}%, "
            f"≥{COLOR_RECOMMEND_MIN_AGREEMENT}/6 nguồn đồng hướng; sau khi đủ "
            f"{COLOR_CALIBRATION_MIN_SAMPLES} mẫu/vùng còn yêu cầu WR thực tế ≥{COLOR_RECOMMEND_MIN_CALIBRATED_WR:.0f}%."
        )
        return "\n".join(lines)

    async def status_text(self) -> str:
        text = await super().status_text()
        if await self.auto_mode_enabled():
            text += (
                f"\n🎨 <b>COLOR ENGINE V{APP_VERSION}</b>: AUTO đang dự đoán XANH/ĐỎ từ nến M5 đã đóng"
                f"\n🗂 Lịch sử tối đa: <b>{COLOR_HISTORY_CANDLES}</b> M5 • không dùng nến live làm feature"
            )
        return text

    async def _send_auto_mode_menu(self) -> int:
        stats = await self.mode_stats_since_reset()
        auto = await self.auto_mode_enabled()
        current = await self.current_analysis_mode()
        labels = [
            ("AUTO", "CÂN BẰNG"), ("M1", "M1 NHANH"), ("M5", "M5 CHẮC"),
            ("AGREE", "ĐỒNG THUẬN M1+M5"), ("MOMENTUM", "ĐỘNG LƯỢNG"),
            ("STRUCTURE", "CẤU TRÚC GIÁ"), ("WICK", "ÁP LỰC RÂU NẾN"),
            ("PATTERN", "MẪU 24H"), ("BREAKOUT", "BỨT PHÁ"),
        ]
        buttons = [[{
            "text": ("✅ " if auto else "") + "🎨 AUTO MÀU NẾN V3.7",
            "callback_data": "mode_auto_best",
        }]]
        for value, label in labels:
            selected = (not auto) and value == current
            buttons.append([{
                "text": self.telegram._mode_button_text(label, selected, stats.get(value)),
                "callback_data": f"mode_{value.lower()}",
            }])
        result = await self.telegram._call("sendMessage", {
            "chat_id": self.telegram.chat_id,
            "text": (
                "🧠 <b>CHỌN CHẾ ĐỘ</b>\n\n"
                "🎨 AUTO MÀU NẾN: chỉ dự đoán cây M5 sẽ đóng XANH hay ĐỎ bằng lịch sử nến đã đóng. "
                "kNN + chuỗi màu + thân + Close + râu + regime được ghép thành một dự đoán.\n"
                "Chọn một mode cũ bên dưới sẽ chuyển sang chế độ thủ công."
            ),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": buttons},
        })
        return int(result["message_id"])
