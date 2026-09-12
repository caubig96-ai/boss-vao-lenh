from __future__ import annotations

import asyncio
import logging
import os

import runtime_v36 as v36
from indicators import all_mode_predictions, analysis_mode_label
from models import Prediction


APP_VERSION = "3.6.1"
ADAPTIVE_INVERT_MIN_SAMPLES = max(2, int(os.getenv("ADAPTIVE_INVERT_MIN_SAMPLES", "20")))
ADAPTIVE_INVERT_BELOW_WIN_RATE = float(os.getenv("ADAPTIVE_INVERT_BELOW_WIN_RATE", "50.0"))
ADAPTIVE_RECOMMEND_MIN_EFFECTIVE_RATE = float(os.getenv("ADAPTIVE_RECOMMEND_MIN_EFFECTIVE_RATE", "55.0"))
ADAPTIVE_SEQUENCE_TOP_MODES = max(1, int(os.getenv("ADAPTIVE_SEQUENCE_TOP_MODES", "3")))

log = logging.getLogger("boss-vao-lenh-v361")

# Keep only the visible inherited runtime version current. Older release modules
# retain their frozen APP_VERSION constants for regression tests.
v36.v357.v356.v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


def adaptive_mode_stats(row: dict | None) -> dict:
    """Return raw and contrarian-adjusted history for one shadow mode.

    Shadow mode_signals always remain RAW. When a proven mode is below 50% WR,
    AUTO interprets its current direction in reverse. The effective historical WR
    is therefore 100 - raw WR, without rewriting the raw shadow history.
    """
    row = row or {}
    wins = int(row.get("wins", 0))
    losses = int(row.get("losses", 0))
    ties = int(row.get("ties", 0))
    decided = int(row.get("decided", wins + losses))
    raw_rate = float(row.get("win_rate", (wins / decided * 100.0) if decided else 0.0))
    inverted = decided >= ADAPTIVE_INVERT_MIN_SAMPLES and raw_rate < ADAPTIVE_INVERT_BELOW_WIN_RATE
    effective_rate = (100.0 - raw_rate) if inverted else raw_rate
    return {
        "wins": losses if inverted else wins,
        "losses": wins if inverted else losses,
        "ties": ties,
        "decided": decided,
        "total": decided + ties,
        "raw_wins": wins,
        "raw_losses": losses,
        "raw_win_rate": raw_rate,
        "win_rate": effective_rate,
        "effective_win_rate": effective_rate,
        "inverted": inverted,
    }


def adapted_direction(direction: str | None, info: dict) -> str | None:
    if direction not in {"UP", "DOWN"}:
        return None
    return v36.opposite(direction) if bool(info.get("inverted")) else direction


def select_adaptive_mode(stats: dict[str, dict]) -> tuple[str, dict]:
    """Choose the mode with the strongest effective WR after optional inversion."""
    rows = [(mode, adaptive_mode_stats(row)) for mode, row in stats.items()]
    eligible = [(mode, info) for mode, info in rows if int(info["decided"]) >= ADAPTIVE_INVERT_MIN_SAMPLES]
    if eligible:
        return max(
            eligible,
            key=lambda item: (float(item[1]["effective_win_rate"]), int(item[1]["decided"])),
        )
    available = [(mode, info) for mode, info in rows if int(info["decided"]) > 0]
    if available:
        # Warm-up: do not invert yet; prefer the largest sample, then raw WR.
        return max(
            available,
            key=lambda item: (int(item[1]["decided"]), float(item[1]["raw_win_rate"])),
        )
    return "AUTO", adaptive_mode_stats(None)


def adaptive_consensus_is_recommended(
    primary_direction: str,
    primary_info: dict,
    sequence_direction: str | None,
    current_vote_direction: str | None,
) -> bool:
    """MUA NGAY only when adaptive history + sequence + live mode vote agree."""
    if int(primary_info.get("decided", 0)) < ADAPTIVE_INVERT_MIN_SAMPLES:
        return False
    if float(primary_info.get("effective_win_rate", 0.0)) < ADAPTIVE_RECOMMEND_MIN_EFFECTIVE_RATE:
        return False
    if sequence_direction != primary_direction:
        return False
    if current_vote_direction != primary_direction:
        return False
    return True


class TradingSignalBotV3(v36.TradingSignalBotV3):
    """V3.6.1: auto-reverse statistically losing modes before consensus.

    All nine shadow modes are still stored and scored in their RAW direction. AUTO
    converts a mode below 50% WR into a contrarian direction only after enough
    settled samples. It then ranks modes by effective WR and requires the adapted
    recent sequence plus the adapted current multi-mode vote to agree before the
    second Telegram message says MUA ... NGAY.
    """

    async def current_analysis_mode(self) -> str:
        if not await self.auto_mode_enabled():
            return await v36.v357.TradingSignalBotV3.current_analysis_mode(self)
        mode, _info = select_adaptive_mode(await self._mode_stats_raw())
        return mode

    async def _adaptive_sequence_vote(self, stats: dict[str, dict], open_time: int) -> dict:
        ranked: list[tuple[str, dict]] = []
        for mode, row in stats.items():
            info = adaptive_mode_stats(row)
            if int(info["decided"]) >= ADAPTIVE_INVERT_MIN_SAMPLES:
                ranked.append((mode, info))
        ranked.sort(
            key=lambda item: (float(item[1]["effective_win_rate"]), int(item[1]["decided"])),
            reverse=True,
        )

        votes = {"UP": 0.0, "DOWN": 0.0}
        details: list[dict] = []
        for mode, info in ranked[:ADAPTIVE_SEQUENCE_TOP_MODES]:
            raw_history = await self._recent_mode_directions(mode, open_time, 4)
            history = [adapted_direction(direction, info) for direction in raw_history]
            expected, pattern = v36.next_from_sequence([d for d in history if d])
            if expected is None:
                continue
            weight = max(0.01, float(info["effective_win_rate"]) / 100.0)
            votes[expected] += weight
            details.append({
                "mode": mode,
                "expected": expected,
                "pattern": pattern,
                "raw_win_rate": float(info["raw_win_rate"]),
                "effective_win_rate": float(info["effective_win_rate"]),
                "inverted": bool(info["inverted"]),
                "decided": int(info["decided"]),
            })

        if not details or abs(votes["UP"] - votes["DOWN"]) < 1e-9:
            direction = None
        else:
            direction = "UP" if votes["UP"] > votes["DOWN"] else "DOWN"
        return {"direction": direction, "votes": votes, "details": details}

    async def _adaptive_current_vote(self, stats: dict[str, dict], open_time: int) -> dict:
        votes = {"UP": 0.0, "DOWN": 0.0}
        details: list[dict] = []
        for mode, row in stats.items():
            info = adaptive_mode_stats(row)
            if int(info["decided"]) < ADAPTIVE_INVERT_MIN_SAMPLES:
                continue
            raw_direction = await self._current_mode_direction(mode, open_time)
            direction = adapted_direction(raw_direction, info)
            if direction is None:
                continue
            weight = max(0.01, float(info["effective_win_rate"]) / 100.0)
            votes[direction] += weight
            details.append({
                "mode": mode,
                "raw_direction": raw_direction,
                "direction": direction,
                "inverted": bool(info["inverted"]),
                "raw_win_rate": float(info["raw_win_rate"]),
                "effective_win_rate": float(info["effective_win_rate"]),
            })
        if not details or abs(votes["UP"] - votes["DOWN"]) < 1e-9:
            direction = None
        else:
            direction = "UP" if votes["UP"] > votes["DOWN"] else "DOWN"
        return {"direction": direction, "votes": votes, "details": details}

    async def _adaptive_snapshot(self, p) -> dict:
        stats = await self._mode_stats_raw()
        mode, info = select_adaptive_mode(stats)
        sequence = await self._adaptive_sequence_vote(stats, int(p.market_open_time))
        current_vote = await self._adaptive_current_vote(stats, int(p.market_open_time))
        recommended = adaptive_consensus_is_recommended(
            p.direction,
            info,
            sequence.get("direction"),
            current_vote.get("direction"),
        )
        return {
            "mode": mode,
            "info": info,
            "sequence": sequence,
            "current_vote": current_vote,
            "recommended": recommended,
        }

    async def _signal_calibration(self, p):
        if not await self.auto_mode_enabled():
            return await v36.v357.TradingSignalBotV3._signal_calibration(self, p)
        snap = await self._adaptive_snapshot(p)
        return dict(snap["info"]), bool(snap["recommended"])

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
                    await self.db.event("DECISION_SKIPPED_NO_MARKET", {"open_time": open_time})
                    return
                if self.live_price <= 0:
                    self.live_price = live.close
                target = live.open

                # Keep RAW shadow signals untouched so a losing mode cannot erase
                # the evidence that caused AUTO to invert it.
                predictions = all_mode_predictions(list(self.m1), list(self.m5), self.live_price, target)
                await self.db.create_mode_signals(open_time, live.close_time, target, predictions)

                stats = await self._mode_stats_raw()
                mode, info = select_adaptive_mode(stats)
                raw_direction, confidence, p1, p5, samples = predictions.get(mode, predictions["AUTO"])
                direction = adapted_direction(raw_direction, info) or raw_direction
                inverted = bool(info.get("inverted"))
                if inverted:
                    # Keep selected-row M1/M5 probabilities aligned with the
                    # effective side. Raw shadow rows stay unchanged.
                    p1 = 1.0 - float(p1)
                    p5 = 1.0 - float(p5)

                actual = await self.signals_enabled()
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
                self.last_decision_state = "ĐÃ TẠO LỆNH AUTO ĐẢO" if inverted else "ĐÃ TẠO LỆNH AUTO"

                row = await self._row_for_signal(open_time)
                if row is not None and bool(row["actual"]) and row["telegram_message_id"] is None:
                    self.telegram.detail_open_time = open_time
                    try:
                        message_id = await self.telegram.send(
                            await self.signal_text(self._prediction_from_row(row)),
                            enabled=True,
                        )
                        await self.db.update_message_id(open_time, message_id)
                        self.last_decision_state = "ĐÃ GỬI TELEGRAM AUTO ĐẢO" if inverted else "ĐÃ GỬI TELEGRAM AUTO"
                    finally:
                        self.telegram.detail_open_time = None

                await self.db.event("ADAPTIVE_DECISION_CREATED", {
                    "open_time": open_time,
                    "mode": mode,
                    "raw_direction": raw_direction,
                    "direction": direction,
                    "inverted": inverted,
                    "raw_win_rate": float(info.get("raw_win_rate", 0.0)),
                    "effective_win_rate": float(info.get("effective_win_rate", 0.0)),
                    "decided": int(info.get("decided", 0)),
                    "created": created,
                    "actual": bool(actual),
                })
            except Exception as exc:
                self.last_decision_state = f"LỖI: {type(exc).__name__}"
                log.exception("Adaptive decision failed for %s", open_time)
                try:
                    await self.db.event("ADAPTIVE_DECISION_ERROR", {"open_time": open_time, "error": str(exc)})
                except Exception:
                    pass
            finally:
                self.decision_tasks.pop(open_time, None)

            # Message 2: exactly once, using adaptive consensus. The inherited
            # action formatter will say MUA ... NGAY only when _signal_calibration
            # reports recommended=True; otherwise it says KHÔNG NÊN VÀO LỆNH.
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
        # Bypass V3.6's old raw best/worst block and show the adaptive interpretation.
        base = await v36.v357.TradingSignalBotV3.detail_signal_text(self, p)
        if not await self.auto_mode_enabled():
            return base + "\n\n🧠 <b>V3.6.1: ĐANG DÙNG CHẾ ĐỘ THỦ CÔNG</b>"
        snap = await self._adaptive_snapshot(p)
        info = snap["info"]
        seq = snap["sequence"]["direction"]
        vote = snap["current_vote"]["direction"]
        side = "TĂNG" if p.direction == "UP" else "GIẢM"
        seq_side = "TĂNG" if seq == "UP" else ("GIẢM" if seq == "DOWN" else "CHƯA RÕ")
        vote_side = "TĂNG" if vote == "UP" else ("GIẢM" if vote == "DOWN" else "CHƯA RÕ")
        if info["inverted"]:
            rate_line = (
                f"↩️ WR gốc <b>{info['raw_win_rate']:.1f}%</b> → đảo lệnh thành "
                f"<b>{info['effective_win_rate']:.1f}% lịch sử đối ứng</b>"
            )
        else:
            rate_line = f"📈 WR gốc/effective: <b>{info['effective_win_rate']:.1f}%</b>"
        verdict = "✅ CÙNG HƯỚNG - NÊN VÀO" if snap["recommended"] else "⚠️ CHƯA CÙNG HƯỚNG - KHÔNG NÊN VÀO"
        return (
            base
            + "\n\n🤖 <b>AUTO ĐẢO THỐNG KÊ V3.6.1</b>"
            + f"\n🏆 Mode chọn: <b>{analysis_mode_label(snap['mode'])}</b> • {int(info['decided'])} mẫu"
            + f"\n{rate_line}"
            + f"\n🎯 Hướng sau thích nghi: <b>{side}</b>"
            + f"\n🔁 Chuỗi gần đây: <b>{seq_side}</b>"
            + f"\n🧠 Phiếu các mode hiện tại: <b>{vote_side}</b>"
            + f"\n{verdict}"
        )

    async def threshold_stats_text(self) -> str:
        inherited = await v36.v357.TradingSignalBotV3.threshold_stats_text(self)
        stats = await self._mode_stats_raw()
        mode, info = select_adaptive_mode(stats)
        lines = [
            "",
            "↩️ <b>AUTO ĐẢO THỐNG KÊ V3.6.1</b>",
            f"🏆 Đang ưu tiên: <b>{analysis_mode_label(mode)}</b>",
            f"Raw WR: <b>{info['raw_win_rate']:.1f}%</b> • Effective: <b>{info['effective_win_rate']:.1f}%</b> • {int(info['decided'])} mẫu",
            f"Đảo tự động khi có ≥{ADAPTIVE_INVERT_MIN_SAMPLES} mẫu và raw WR <{ADAPTIVE_INVERT_BELOW_WIN_RATE:.0f}%.",
            f"MUA NGAY cần effective ≥{ADAPTIVE_RECOMMEND_MIN_EFFECTIVE_RATE:.0f}% + chuỗi + phiếu mode cùng hướng.",
        ]
        return inherited + "\n" + "\n".join(lines)

    async def status_text(self) -> str:
        text = await v36.v357.TradingSignalBotV3.status_text(self)
        if not await self.auto_mode_enabled():
            return text + "\n🤖 Auto đảo: <b>TẮT - đang chọn tay</b>"
        mode, info = select_adaptive_mode(await self._mode_stats_raw())
        state = "ĐẢO" if info["inverted"] else "THUẬN"
        return (
            text
            + f"\n🤖 Auto đảo: <b>BẬT</b> • <b>{analysis_mode_label(mode)}</b> • {state}"
            + f" • raw {info['raw_win_rate']:.1f}% → effective {info['effective_win_rate']:.1f}%"
            + "\n♾️ Sau lệnh thua: <b>KHÔNG TẠM NGHỈ 30 PHÚT</b>"
        )

    async def _send_auto_mode_menu(self) -> int:
        stats = await self._mode_stats_raw()
        auto = await self.auto_mode_enabled()
        current = await self.current_analysis_mode()
        labels = [
            ("AUTO", "CÂN BẰNG"), ("M1", "M1 NHANH"), ("M5", "M5 CHẮC"),
            ("AGREE", "ĐỒNG THUẬN M1+M5"), ("MOMENTUM", "ĐỘNG LƯỢNG"),
            ("STRUCTURE", "CẤU TRÚC GIÁ"), ("WICK", "ÁP LỰC RÂU NẾN"),
            ("PATTERN", "MẪU 24H"), ("BREAKOUT", "BỨT PHÁ"),
        ]
        buttons = [[{
            "text": ("✅ " if auto else "") + "🤖 TỰ CHỌN + TỰ ĐẢO + ĐỒNG THUẬN",
            "callback_data": "mode_auto_best",
        }]]
        for value, label in labels:
            row = stats.get(value, {})
            info = adaptive_mode_stats(row)
            selected = (not auto) and value == current
            prefix = "✅ " if selected else ""
            if int(info["decided"]) <= 0:
                text = f"{prefix}{label} · 0T/0B · --"
            elif info["inverted"]:
                text = (
                    f"{prefix}{label} · {info['raw_wins']}T/{info['raw_losses']}B · "
                    f"{info['raw_win_rate']:.1f}% ↩ {info['effective_win_rate']:.1f}%"
                )
            else:
                text = (
                    f"{prefix}{label} · {info['raw_wins']}T/{info['raw_losses']}B · "
                    f"{info['raw_win_rate']:.1f}%"
                )
            buttons.append([{"text": text, "callback_data": f"mode_{value.lower()}"}])
        result = await self.telegram._call("sendMessage", {
            "chat_id": self.telegram.chat_id,
            "text": (
                "🧠 <b>CHỌN CHẾ ĐỘ</b>\n\n"
                "🤖 AUTO: mode có lịch sử thua nhiều (<50%) và đủ mẫu sẽ được ĐẢO TĂNG↔GIẢM. "
                "Bot xếp hạng theo tỷ lệ hiệu dụng sau đảo, rồi chỉ khuyên vào khi chuỗi và các mode hiện tại cùng hướng.\n"
                "↩ trên nút = tỷ lệ gốc → tỷ lệ lịch sử đối ứng sau đảo.\n"
                "Chọn một mode riêng sẽ chuyển sang thủ công."
            ),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": buttons},
        })
        return int(result["message_id"])
