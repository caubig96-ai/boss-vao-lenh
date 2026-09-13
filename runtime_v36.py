from __future__ import annotations

import os

import runtime_v357 as v357
from indicators import ANALYSIS_MODES, analysis_mode_label, normalize_analysis_mode


APP_VERSION = "3.6.0"
AUTO_MODE_MIN_SAMPLES = max(2, int(os.getenv("AUTO_MODE_MIN_SAMPLES", "8")))
WORST_INVERT_MAX_WIN_RATE = float(os.getenv("WORST_INVERT_MAX_WIN_RATE", "45.0"))
BEST_MIN_WIN_RATE = float(os.getenv("BEST_MIN_WIN_RATE", "50.0"))

# Keep the visible base runtime version current without changing frozen older
# module constants used by their regression tests.
v357.v356.v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


def opposite(direction: str | None) -> str | None:
    if direction == "UP":
        return "DOWN"
    if direction == "DOWN":
        return "UP"
    return None


def next_from_sequence(directions: list[str]) -> tuple[str | None, str]:
    """Predict the next side from immediate neighboring mode directions.

    User rule:
    - X X -> X (two greens continue green)
    - D D -> D
    - X D -> X (alternate back to green)
    - D X -> D
    Four-step X D X D / D X D X is labeled as a stronger alternating pattern.
    """
    clean = [item for item in directions if item in {"UP", "DOWN"}]
    if len(clean) < 2:
        return None, "CHƯA ĐỦ CHUỖI"
    last2 = clean[-2:]
    if last2[0] == last2[1]:
        return last2[-1], "2 CÙNG MÀU LIỀN NHAU"
    if len(clean) >= 4:
        last4 = clean[-4:]
        if all(last4[i] != last4[i + 1] for i in range(3)):
            return opposite(last4[-1]), "XEN KẼ 4 NẾN"
    return opposite(last2[-1]), "XEN KẼ 2 NẾN"


def select_best_worst(stats: dict[str, dict]) -> tuple[str, str | None]:
    """Select the best proven mode and the worst proven mode from settled history."""
    eligible = [
        (mode, row)
        for mode, row in stats.items()
        if int(row.get("decided", 0)) >= AUTO_MODE_MIN_SAMPLES
    ]
    if not eligible:
        # During warm-up choose the mode with the most history, then best WR.
        available = [(mode, row) for mode, row in stats.items() if int(row.get("decided", 0)) > 0]
        if not available:
            return "AUTO", None
        best_mode = max(
            available,
            key=lambda item: (int(item[1].get("decided", 0)), float(item[1].get("win_rate", 0.0))),
        )[0]
        return best_mode, None

    best_mode = max(
        eligible,
        key=lambda item: (float(item[1].get("win_rate", 0.0)), int(item[1].get("decided", 0))),
    )[0]
    worst_mode, worst_row = min(
        eligible,
        key=lambda item: (float(item[1].get("win_rate", 0.0)), -int(item[1].get("decided", 0))),
    )
    if worst_mode == best_mode or float(worst_row.get("win_rate", 100.0)) > WORST_INVERT_MAX_WIN_RATE:
        worst_mode = None
    return best_mode, worst_mode


def consensus_is_recommended(
    best_direction: str,
    best_stats: dict,
    sequence_direction: str | None,
    inverse_worst_direction: str | None,
) -> bool:
    """Recommend only when historical edge and direction-pattern evidence agree."""
    decided = int(best_stats.get("decided", 0))
    win_rate = float(best_stats.get("win_rate", 0.0))
    if decided < AUTO_MODE_MIN_SAMPLES or win_rate <= BEST_MIN_WIN_RATE:
        return False
    if sequence_direction is None or sequence_direction != best_direction:
        return False
    if inverse_worst_direction is not None and inverse_worst_direction != best_direction:
        return False
    return True


class TradingSignalBotV3(v357.TradingSignalBotV3):
    """V3.6: automatic best-mode + direction-sequence consensus.

    The bot keeps all nine shadow modes. In AUTO mode it selects the mode with the
    strongest settled W/L rate, confirms the current direction against recent mode
    direction sequences, and optionally uses the worst mode as a contrarian vote.
    Every M5 signal is still reported; MUA ... NGAY is reserved for aligned evidence.
    The old automatic 30-minute pause after two losses is disabled.
    """

    async def setup(self) -> None:
        await super().setup()
        await self.db.set_default("auto_mode_enabled", "1")
        # A database upgraded while an old 30-minute pause is active must resume
        # immediately under V3.6.
        await self.db.set("risk_pause_until", "0")
        await self.db.set("risk_cycle_losses", "0")

    async def signals_enabled(self) -> bool:
        """Only the manual STOP button can suppress normal M5 messages in V3.6."""
        await self.db.set("risk_pause_until", "0")
        return await self.db.get("manual_enabled", "1") == "1"

    async def apply_money_management(self, row, result: str, pnl: float) -> None:
        """Keep balance/bet-step tracking but never start a loss cooldown."""
        balance = float(await self.db.get("current_balance", "0")) + pnl
        await self.db.set("current_balance", f"{balance:.8f}")
        step = int(row["bet_step"])
        await self.db.set("bet_step", 2 if step == 1 and result == "WIN" else 1)
        await self.db.set("risk_cycle_losses", "0")
        await self.db.set("risk_pause_until", "0")

    async def auto_mode_enabled(self) -> bool:
        return await self.db.get("auto_mode_enabled", "1") == "1"

    async def _mode_stats_raw(self) -> dict[str, dict]:
        reset_at = int(await self.db.get("stats_reset_at", "0"))
        return await self.db.mode_stats(max(0, reset_at))

    async def current_analysis_mode(self) -> str:
        if not await self.auto_mode_enabled():
            return normalize_analysis_mode(await self.db.get("analysis_mode", "AUTO"))
        stats = await self._mode_stats_raw()
        best, _worst = select_best_worst(stats)
        return best

    async def _recent_mode_directions(self, mode: str, before_open_time: int, limit: int = 4) -> list[str]:
        rows = await (await self.db.conn.execute(
            """SELECT direction FROM mode_signals
               WHERE mode=? AND market_open_time<? AND status='SETTLED'
               ORDER BY market_open_time DESC LIMIT ?""",
            (mode, before_open_time, limit),
        )).fetchall()
        return [row["direction"] for row in reversed(rows)]

    async def _current_mode_direction(self, mode: str, open_time: int) -> str | None:
        row = await (await self.db.conn.execute(
            "SELECT direction FROM mode_signals WHERE mode=? AND market_open_time=?",
            (mode, open_time),
        )).fetchone()
        return row["direction"] if row else None

    async def _sequence_vote(self, stats: dict[str, dict], open_time: int) -> dict:
        """Weighted vote from recent patterns of the three strongest proven modes."""
        eligible = [
            (mode, row)
            for mode, row in stats.items()
            if int(row.get("decided", 0)) >= AUTO_MODE_MIN_SAMPLES
        ]
        eligible.sort(
            key=lambda item: (float(item[1].get("win_rate", 0.0)), int(item[1].get("decided", 0))),
            reverse=True,
        )
        votes = {"UP": 0.0, "DOWN": 0.0}
        details: list[dict] = []
        for mode, row in eligible[:3]:
            history = await self._recent_mode_directions(mode, open_time, 4)
            expected, pattern = next_from_sequence(history)
            if expected is None:
                continue
            weight = max(0.01, float(row.get("win_rate", 0.0)) / 100.0)
            votes[expected] += weight
            details.append({
                "mode": mode,
                "expected": expected,
                "pattern": pattern,
                "win_rate": float(row.get("win_rate", 0.0)),
                "decided": int(row.get("decided", 0)),
            })
        if not details or abs(votes["UP"] - votes["DOWN"]) < 1e-9:
            direction = None
        else:
            direction = "UP" if votes["UP"] > votes["DOWN"] else "DOWN"
        return {"direction": direction, "votes": votes, "details": details}

    async def _consensus_snapshot(self, p) -> dict:
        stats = await self._mode_stats_raw()
        best_mode, worst_mode = select_best_worst(stats)
        best_stats = stats.get(best_mode, {"wins": 0, "losses": 0, "ties": 0, "decided": 0, "win_rate": 0.0})
        sequence = await self._sequence_vote(stats, int(p.market_open_time))

        inverse_worst = None
        worst_direction = None
        worst_stats = None
        if worst_mode:
            worst_stats = stats.get(worst_mode)
            worst_direction = await self._current_mode_direction(worst_mode, int(p.market_open_time))
            inverse_worst = opposite(worst_direction)

        recommended = consensus_is_recommended(
            p.direction,
            best_stats,
            sequence.get("direction"),
            inverse_worst,
        )
        return {
            "best_mode": best_mode,
            "best_stats": best_stats,
            "sequence": sequence,
            "worst_mode": worst_mode,
            "worst_stats": worst_stats,
            "worst_direction": worst_direction,
            "inverse_worst": inverse_worst,
            "recommended": recommended,
        }

    async def _signal_calibration(self, p):
        """Feed V3.5 compact UI with V3.6 empirical auto-consensus quality."""
        if not await self.auto_mode_enabled():
            return await super()._signal_calibration(p)
        snap = await self._consensus_snapshot(p)
        stats = dict(snap["best_stats"])
        stats.setdefault("decided", 0)
        stats.setdefault("win_rate", 0.0)
        return stats, bool(snap["recommended"])

    async def detail_signal_text(self, p) -> str:
        base = await super().detail_signal_text(p)
        if not await self.auto_mode_enabled():
            return base + "\n\n🧠 <b>V3.6: ĐANG DÙNG CHẾ ĐỘ THỦ CÔNG</b>"
        snap = await self._consensus_snapshot(p)
        best = snap["best_stats"]
        seq = snap["sequence"]
        best_side = "TĂNG" if p.direction == "UP" else "GIẢM"
        seq_side = "TĂNG" if seq["direction"] == "UP" else ("GIẢM" if seq["direction"] == "DOWN" else "CHƯA RÕ")
        if snap["worst_mode"]:
            inverse_side = "TĂNG" if snap["inverse_worst"] == "UP" else "GIẢM"
            worst_line = (
                f"\n↩️ Mode yếu nhất: <b>{analysis_mode_label(snap['worst_mode'])}</b> "
                f"{float(snap['worst_stats'].get('win_rate', 0.0)):.1f}% → đảo thành <b>{inverse_side}</b>"
            )
        else:
            worst_line = "\n↩️ Mode yếu nhất: chưa đủ điều kiện để dùng tín hiệu đảo"
        verdict = "✅ CÙNG HƯỚNG - NÊN VÀO" if snap["recommended"] else "⚠️ CHƯA CÙNG HƯỚNG - KHÔNG NÊN VÀO"
        return (
            base
            + "\n\n🤖 <b>AUTO CONSENSUS V3.6</b>"
            + f"\n🏆 Mode tốt nhất: <b>{analysis_mode_label(snap['best_mode'])}</b> "
              f"{float(best.get('win_rate', 0.0)):.1f}% ({int(best.get('wins', 0))}T/{int(best.get('losses', 0))}B) → <b>{best_side}</b>"
            + f"\n🔁 Xu hướng chuỗi mode tốt: <b>{seq_side}</b>"
            + worst_line
            + f"\n{verdict}"
        )

    async def threshold_stats_text(self) -> str:
        inherited = await super().threshold_stats_text()
        stats = await self._mode_stats_raw()
        best, worst = select_best_worst(stats)
        best_row = stats.get(best, {})
        lines = [
            "",
            "🤖 <b>TỰ CHỌN CHẾ ĐỘ V3.6</b>",
            f"🏆 Tốt nhất hiện tại: <b>{analysis_mode_label(best)}</b> • {float(best_row.get('win_rate', 0.0)):.1f}% • {int(best_row.get('decided', 0))} mẫu",
        ]
        if worst:
            row = stats.get(worst, {})
            lines.append(
                f"↩️ Yếu nhất để xét đảo: <b>{analysis_mode_label(worst)}</b> • {float(row.get('win_rate', 0.0)):.1f}% • {int(row.get('decided', 0))} mẫu"
            )
        lines.append(
            f"Điều kiện dữ liệu auto: tối thiểu {AUTO_MODE_MIN_SAMPLES} mẫu/mode; mode yếu chỉ đảo khi WR ≤{WORST_INVERT_MAX_WIN_RATE:.0f}%."
        )
        return inherited + "\n" + "\n".join(lines)

    async def status_text(self) -> str:
        text = await super().status_text()
        auto = await self.auto_mode_enabled()
        if auto:
            stats = await self._mode_stats_raw()
            best, worst = select_best_worst(stats)
            extra = f"\n🤖 Auto mode: <b>BẬT</b> • đang ưu tiên <b>{analysis_mode_label(best)}</b>"
            if worst:
                extra += f" • xét đảo <b>{analysis_mode_label(worst)}</b>"
        else:
            extra = "\n🤖 Auto mode: <b>TẮT - đang chọn tay</b>"
        return text + extra + "\n♾️ Sau lệnh thua: <b>KHÔNG TẠM NGHỈ 30 PHÚT</b>"

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
            "text": ("✅ " if auto else "") + "🤖 TỰ CHỌN MODE + ĐỒNG THUẬN",
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
                "🤖 TỰ CHỌN: bot tự ưu tiên mode có tỷ lệ thắng tốt, kiểm tra chuỗi TĂNG/GIẢM và tín hiệu đảo của mode yếu.\n"
                "Chọn một mode bên dưới sẽ chuyển sang chế độ thủ công."
            ),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": buttons},
        })
        return int(result["message_id"])

    async def handle_telegram(self, kind: str, value: str, update: dict) -> None:
        if kind == "callback" and value == "analysis_mode":
            await self._send_auto_mode_menu()
            return
        if kind == "callback" and value == "mode_auto_best":
            await self.db.set("auto_mode_enabled", "1")
            mode = await self.current_analysis_mode()
            await self.telegram.send(
                f"🤖 <b>ĐÃ BẬT TỰ CHỌN CHẾ ĐỘ</b>\nHiện ưu tiên: <b>{analysis_mode_label(mode)}</b>."
            )
            return
        if kind == "callback" and value.startswith("mode_"):
            await self.db.set("auto_mode_enabled", "0")
            return await super().handle_telegram(kind, value, update)
        if kind == "message":
            parts = value.strip().split()
            if len(parts) == 2 and parts[0].lower() in {"/mode", "/modes"} and parts[1].lower() in {"auto", "best", "tudong", "tựđộng"}:
                await self.db.set("auto_mode_enabled", "1")
                mode = await self.current_analysis_mode()
                await self.telegram.send(f"🤖 Auto mode: <b>BẬT</b> • ưu tiên <b>{analysis_mode_label(mode)}</b>")
                return
        await super().handle_telegram(kind, value, update)
