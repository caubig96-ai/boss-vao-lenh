from __future__ import annotations

import asyncio
import os
from datetime import datetime

import runtime_v3 as base_runtime
from indicators import all_mode_predictions, analysis_mode_label, candle_analysis
from models import Prediction
from telegram_v3 import TelegramBotV3


APP_VERSION = "3.3.0"
# PR #10 fixed final scoring to Binance's official M5 OPEN. Do not calibrate
# against older settled rows that may have been scored with a provisional target.
CALIBRATION_START_MS = 1_789_107_533_000


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


CALIBRATION_MIN_SAMPLES = _env_int("CALIBRATION_MIN_SAMPLES", 30)
CALIBRATION_MAX_SAMPLES = _env_int("CALIBRATION_MAX_SAMPLES", 200, CALIBRATION_MIN_SAMPLES)
CALIBRATION_MIN_WIN_RATE = _env_float("CALIBRATION_MIN_WIN_RATE", 70.0)
CALIBRATION_MEDIUM_WIN_RATE = _env_float("CALIBRATION_MEDIUM_WIN_RATE", 60.0)

# Narrow bands let the bot learn whether a raw model score is actually useful.
# The raw score is NOT presented as a calibrated probability anymore.
SCORE_BANDS: tuple[tuple[str, float, float | None], ...] = (
    ("50.0–54.9", 0.50, 0.55),
    ("55.0–59.9", 0.55, 0.60),
    ("60.0–64.9", 0.60, 0.65),
    ("65.0–69.9", 0.65, 0.70),
    ("70.0–74.9", 0.70, 0.75),
    ("75.0+", 0.75, None),
)

# Keep every inherited V3 status/startup message on the same visible version.
base_runtime.APP_VERSION = APP_VERSION


def score_band(confidence: float) -> tuple[str, float, float | None]:
    value = max(0.50, min(0.95, float(confidence)))
    for label, low, high in SCORE_BANDS:
        if high is None or value < high:
            if value >= low:
                return label, low, high
    return SCORE_BANDS[-1]


async def _calibration_for_band(db, mode: str, label: str, low: float, high: float | None) -> dict:
    params: list[object] = [mode, CALIBRATION_START_MS, low]
    upper_sql = ""
    if high is not None:
        upper_sql = " AND confidence<?"
        params.append(high)
    params.append(CALIBRATION_MAX_SAMPLES)
    rows = await (await db.conn.execute(
        f"""SELECT result FROM mode_signals
            WHERE mode=? AND status='SETTLED' AND market_open_time>=?
              AND confidence>=?{upper_sql}
            ORDER BY market_open_time DESC
            LIMIT ?""",
        tuple(params),
    )).fetchall()
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


async def calibration_stats(db, mode: str, confidence: float) -> dict:
    label, low, high = score_band(confidence)
    return await _calibration_for_band(db, mode, label, low, high)


async def calibration_table(db, mode: str) -> list[dict]:
    result: list[dict] = []
    for label, low, high in SCORE_BANDS:
        result.append(await _calibration_for_band(db, mode, label, low, high))
    return result


def calibration_quality(stats: dict) -> tuple[str, str, bool]:
    decided = int(stats.get("decided", 0))
    rate = float(stats.get("win_rate", 0.0))
    if decided < CALIBRATION_MIN_SAMPLES:
        return "⚪", "CHƯA ĐỦ MẪU", False
    if rate >= CALIBRATION_MIN_WIN_RATE:
        return "🟢", "CAO", True
    if rate >= CALIBRATION_MEDIUM_WIN_RATE:
        return "🟡", "TRUNG BÌNH", False
    return "🔴", "THẤP", False


class CalibratedTelegramBotV3(TelegramBotV3):
    @staticmethod
    def instant_followup_text(text: str) -> str | None:
        """MUA NGAY is allowed only after empirical calibration, not raw score."""
        if "TIN NHẮN VÀO LỆNH" not in text or "HIỆU CHỈNH: CAO" not in text:
            return None
        if "𝗠𝗨𝗔 𝗧Ă𝗡𝗚" in text or "MUA TĂNG" in text:
            return "🚨 <b>MUA TĂNG NGAY</b>"
        if "𝗠𝗨𝗔 𝗚𝗜Ả𝗠" in text or "MUA GIẢM" in text:
            return "🚨 <b>MUA GIẢM NGAY</b>"
        return None


class TradingSignalBotV3(base_runtime.TradingSignalBotV3):
    """V3.3: raw model score + empirical calibration before sending real signals.

    All nine modes still analyze every M5 session in shadow. The selected mode is
    promoted to a real Telegram entry only when its SAME mode + SAME score band
    has enough post-fix settled history and observed win rate reaches the configured
    threshold (70% by default). This does not claim future 70% accuracy.
    """

    def __init__(self, config):
        super().__init__(config)
        self.telegram = CalibratedTelegramBotV3(
            config.telegram_token,
            config.telegram_chat_id,
            self.handle_telegram,
            self._save_telegram_offset,
        )

    async def make_decision(self, open_time: int, delay: float) -> None:
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
                await self.db.event("DECISION_SKIPPED_NO_MARKET", {"open_time": open_time})
                return
            if self.live_price <= 0:
                self.live_price = live.close
            target = live.open

            # Keep learning on ALL nine modes every M5 session, even when no entry
            # is sent. Calibration reads only already-settled rows, so this session
            # can never leak its own result into the decision.
            predictions = all_mode_predictions(list(self.m1), list(self.m5), self.live_price, target)
            await self.db.create_mode_signals(open_time, live.close_time, target, predictions)

            mode = await self.current_analysis_mode()
            direction, confidence, p1, p5, samples = predictions[mode]
            calibrated = await calibration_stats(self.db, mode, confidence)
            _, quality, qualified = calibration_quality(calibrated)
            manual_ok = await self.signals_enabled()
            actual = bool(manual_ok and qualified)

            base_bet = float(await self.db.get("base_bet", str(self.config.base_bet)))
            step = int(await self.db.get("bet_step", "1"))
            bet = min(base_bet * (2 if step == 2 else 1), self.config.max_bet)
            prediction = Prediction(
                open_time,
                live.close_time,
                target,
                self.live_price,
                direction,
                confidence,
                p1,
                p5,
                samples,
                bet,
                step,
                actual,
            )
            created = await self.db.create_signal(prediction)
            self.last_decision_open = open_time

            if actual:
                self.last_decision_state = "ĐÃ TẠO LỆNH ĐỦ ĐIỀU KIỆN" if created else "ĐÃ TỒN TẠI"
            elif not manual_ok:
                self.last_decision_state = "PHÂN TÍCH NỀN - GỬI LỆNH ĐANG TẮT/TẠM NGHỈ"
            elif int(calibrated["decided"]) < CALIBRATION_MIN_SAMPLES:
                self.last_decision_state = (
                    f"BỎ QUA: {calibrated['decided']}/{CALIBRATION_MIN_SAMPLES} MẪU "
                    f"({calibrated['band']})"
                )
            else:
                self.last_decision_state = (
                    f"BỎ QUA: WR {calibrated['win_rate']:.1f}% < {CALIBRATION_MIN_WIN_RATE:.1f}% "
                    f"({calibrated['band']})"
                )

            row = await self._row_for_signal(open_time)
            if row is not None and bool(row["actual"]) and row["telegram_message_id"] is None:
                try:
                    message_id = await self.telegram.send(
                        await self.signal_text(self._prediction_from_row(row)),
                        enabled=True,
                    )
                    await self.db.update_message_id(open_time, message_id)
                    self.last_decision_state = "ĐÃ GỬI TELEGRAM"
                except Exception as exc:
                    self.last_decision_state = "ĐÃ TẠO - CHỜ GỬI LẠI TELE"
                    await self.db.event("SIGNAL_SEND_ERROR", {"open_time": open_time, "error": str(exc)})

            await self.db.event("DECISION_CREATED", {
                "open_time": open_time,
                "direction": direction,
                "actual": actual,
                "raw_score": confidence,
                "created": created,
                "analysis_mode": mode,
                "shadow_modes": len(predictions),
                "calibration_band": calibrated["band"],
                "calibration_decided": calibrated["decided"],
                "calibration_win_rate": calibrated["win_rate"],
                "calibration_quality": quality,
                "qualified": qualified,
            })
        except Exception as exc:
            self.last_decision_state = f"LỖI: {type(exc).__name__}"
            base_runtime.log.exception("Decision failed for %s", open_time)
            try:
                await self.db.event("DECISION_ERROR", {"open_time": open_time, "error": str(exc)})
            except Exception:
                pass
        finally:
            self.decision_tasks.pop(open_time, None)

    @staticmethod
    def _calibration_line(stats: dict) -> str:
        icon, _, qualified = calibration_quality(stats)
        decided = int(stats["decided"])
        ties = int(stats["ties"])
        if decided <= 0:
            value = "chưa có kết quả"
        else:
            value = f"<b>{stats['win_rate']:.1f}%</b> ({stats['wins']} thắng/{stats['losses']} thua)"
        if ties:
            value += f" + {ties} hòa"
        if decided < CALIBRATION_MIN_SAMPLES:
            suffix = f" • {decided}/{CALIBRATION_MIN_SAMPLES} mẫu"
        elif qualified:
            suffix = " • ĐỦ ĐIỀU KIỆN"
        else:
            suffix = f" • chưa đạt {CALIBRATION_MIN_WIN_RATE:.0f}%"
        return f"{icon} Score {stats['band']}%: {value}{suffix}"

    async def threshold_stats_text(self) -> str:
        mode = await self.current_analysis_mode()
        rows = await calibration_table(self.db, mode)
        lines = "\n".join(self._calibration_line(row) for row in rows)
        return (
            "📈 <b>HIỆU CHỈNH SCORE THEO KẾT QUẢ THẬT</b>\n"
            f"🧠 Chế độ: <b>{analysis_mode_label(mode)}</b>\n"
            f"{lines}\n"
            f"<i>Score mô hình không phải xác suất thắng. Lệnh thực tế chỉ gửi khi đúng vùng score có ít nhất "
            f"{CALIBRATION_MIN_SAMPLES} kết quả thắng/thua và win rate lịch sử ≥{CALIBRATION_MIN_WIN_RATE:.0f}%. "
            f"Dùng tối đa {CALIBRATION_MAX_SAMPLES} kết quả gần nhất/vùng; hòa không tính vào win rate. "
            "Calibration chỉ dùng dữ liệu sau bản sửa Target/Open chính thức.</i>"
        )

    @staticmethod
    def calibration_block(stats: dict, raw_score: float) -> str:
        icon, quality, _ = calibration_quality(stats)
        decided = int(stats["decided"])
        if decided:
            history = (
                f"{stats['win_rate']:.1f}% ({stats['wins']} thắng/{stats['losses']} thua"
                + (f", {stats['ties']} hòa" if stats["ties"] else "")
                + ")"
            )
        else:
            history = "chưa có dữ liệu"
        return (
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📐 <b>ĐIỂM MÔ HÌNH: {raw_score * 100:.1f}/100</b>\n"
            f"📊 Lịch sử cùng mode + vùng {stats['band']}%: <b>{history}</b>\n"
            f"{icon} <b>HIỆU CHỈNH: {quality}</b> • mẫu quyết định {decided}/{CALIBRATION_MIN_SAMPLES}\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

    async def signal_text(self, p: Prediction) -> str:
        local_open = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp(p.market_close_time / 1000, self.config.timezone)
        label = "🟢 𝗠𝗨𝗔 𝗧Ă𝗡𝗚" if p.direction == "UP" else "🔴 𝗠𝗨𝗔 𝗚𝗜Ả𝗠"
        m1_analysis = candle_analysis(list(self.m1), "M1")
        m5_analysis = candle_analysis(list(self.m5), "M5")
        mode = await self.current_analysis_mode()
        calibrated = await calibration_stats(self.db, mode, p.confidence)
        return (
            f"📥 <b>TIN NHẮN VÀO LỆNH • V{APP_VERSION}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{label}: {p.bet_amount:.2f} USDT</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ Phiên: {local_open:%H:%M}–{local_close:%H:%M}\n"
            f"🎯 Open/Target M5: <code>{p.target_price:,.2f}</code> USDT\n"
            f"💵 Giá lúc báo: <code>{p.signal_price:,.2f}</code> USDT\n"
            f"🧠 Chế độ gửi lệnh: <b>{analysis_mode_label(mode)}</b>\n\n"
            f"{self.calibration_block(calibrated, p.confidence)}\n\n"
            f"🔎 M1 score tăng: {p.m1_probability * 100:.1f}% | M5 score tăng: {p.m5_probability * 100:.1f}%\n"
            f"🕯 {m1_analysis}\n🕯 {m5_analysis}\n"
            f"🧩 Mẫu lịch sử 5 nến: <b>{p.pattern_samples} mẫu tham chiếu</b>\n"
            f"🔢 Tầng tiền: <b>LỆNH {p.bet_step}</b>" + await self.stats_text()
        )

    async def result_text(self, row, close_price: float, result: str, pnl: float) -> str:
        direction = "TĂNG" if row["direction"] == "UP" else "GIẢM"
        headline = {
            "WIN": f"✅ <b>ĐÃ THẮNG {direction}</b>",
            "LOSS": f"❌ <b>ĐÃ THUA {direction}</b>",
            "TIE": f"➖ <b>ĐÃ HÒA {direction}</b>",
        }[result]
        target = float(row["target_price"])
        delta = float(close_price) - target
        return (
            f"{headline}\n"
            f"🎯 Open/Target: <code>{target:,.2f}</code> USDT\n"
            f"🏁 Close M5: <code>{close_price:,.2f}</code> USDT\n"
            f"↕️ Chênh lệch: <code>{delta:+,.2f}</code> USDT"
        )
