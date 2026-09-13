from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

import runtime_v379 as previous
import runtime_v3 as base_runtime
from models import Prediction
from pair_pattern_model import METHODS, STATS_WINDOW, find_pair_matches


APP_VERSION = "3.8.0"
previous.APP_VERSION = APP_VERSION
base_runtime.APP_VERSION = APP_VERSION
log = logging.getLogger("boss-manual-pair-method")

METHOD_LABELS = previous.METHOD_LABELS
DIRECTION_LABELS = previous.DIRECTION_LABELS
RESULT_LABELS = previous.RESULT_LABELS


class TwoMethodTelegramV380(previous.TwoMethodTelegram):
    """Expose an actual two-method selector instead of the legacy 9-mode menu."""

    def keyboard(self, enabled=None):
        base = super().keyboard(enabled)
        rows = list(base.get("inline_keyboard", []))
        method_button = [{"text": "🧠 CHỌN PHƯƠNG PHÁP", "callback_data": "analysis_mode"}]
        if not any(
            button.get("callback_data") == "analysis_mode"
            for row in rows for button in row
        ):
            rows.insert(1 if rows else 0, method_button)
        return {"inline_keyboard": rows}

    @staticmethod
    def _method_button_text(label: str, selected: bool, stats: dict | None) -> str:
        prefix = "✅ " if selected else ""
        if not stats or int(stats.get("decided", 0)) <= 0:
            return f"{prefix}{label} · 0T/0B · --"
        wins = int(stats.get("wins", 0))
        losses = int(stats.get("losses", 0))
        win_rate = float(stats.get("win_rate", 0.0)) * 100
        return f"{prefix}{label} · {wins}T/{losses}B · {win_rate:.1f}%"

    async def send_pair_method_menu(self, current_method: str, stats: dict[str, dict]) -> int:
        current = current_method if current_method in METHODS else "color_pair"
        buttons = []
        for method in METHODS:
            buttons.append([{
                "text": self._method_button_text(
                    METHOD_LABELS[method].upper(), method == current, stats.get(method)
                ),
                "callback_data": f"mode_{method}",
            }])
        result = await self._call("sendMessage", {
            "chat_id": self.chat_id,
            "text": (
                "🧠 <b>CHỌN PHƯƠNG PHÁP GỬI LỆNH</b>\n\n"
                "✅ = phương pháp đang điều khiển lệnh Telegram.\n"
                "Chọn phương pháp nào thì từ phiên 5 phút kế tiếp chỉ phương pháp đó được dùng để tạo lệnh.\n"
                "Phương pháp còn lại vẫn được chấm thắng/thua ở nền để giữ thống kê."
            ),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": buttons},
        })
        return int(result["message_id"])


class TradingSignalBotV3(previous.TradingSignalBotV3):
    """V3.8.0: manual pair method + previous-result conditional priority."""

    def __init__(self, config):
        super().__init__(config)
        self.telegram = TwoMethodTelegramV380(
            config.telegram_token,
            config.telegram_chat_id,
            self.handle_telegram,
            self._save_telegram_offset,
        )

    async def setup(self):
        await super().setup()
        await self.db.set_default("pair_method", "color_pair")

    async def current_pair_method(self) -> str:
        method = await self.db.get("pair_method", "color_pair")
        return method if method in METHODS else "color_pair"

    async def _set_pair_method(self, method: str) -> str:
        selected = method if method in METHODS else "color_pair"
        await self.db.set("pair_method", selected)
        await self.db.event("PAIR_METHOD_CHANGED", {"method": selected})
        return selected

    @staticmethod
    def select_requested_method(matches, stats, method: str):
        """Only the explicitly selected method may control the outgoing signal."""
        if method not in METHODS:
            method = "color_pair"
        match = matches.get(method)
        if match is None or match.raw_direction is None:
            return None
        total = int(match.green_count) + int(match.red_count)
        return {
            "method": method,
            "raw_direction": match.raw_direction,
            "direction": match.raw_direction,
            "inverse": False,
            "effective_rate": max(match.green_count, match.red_count) / total if total else 0.5,
            "match": match.to_dict(),
            "raw_stats": dict(stats[method]),
        }

    @staticmethod
    def priority_from_results(raw_stats: dict, results: list[str]) -> dict:
        """Evaluate next-WIN frequency after the latest result for 50-60% methods.

        The user's 50-60% rule applies whether WIN or LOSS is the larger side, so the
        dominant rate is max(win_rate, loss_rate).  When that rate is in [50%, 60%],
        the latest method result becomes the context.  If historical signals following
        the same context won more often than they lost, the next signal is marked priority.
        """
        clean = [value for value in results if value in ("WIN", "LOSS")]
        previous_result = clean[-1] if clean else None
        after = []
        if previous_result:
            after = [
                current for prior, current in zip(clean, clean[1:])
                if prior == previous_result
            ]
        after_wins = after.count("WIN")
        after_losses = after.count("LOSS")
        samples = after_wins + after_losses
        next_win_rate = after_wins / samples if samples else None
        win_rate = float(raw_stats.get("win_rate", 0.5))
        loss_rate = float(raw_stats.get("loss_rate", 0.5))
        dominant_rate = max(win_rate, loss_rate)
        in_50_60_band = 0.50 <= dominant_rate <= 0.60
        priority = bool(
            in_50_60_band and samples > 0 and next_win_rate is not None and next_win_rate > 0.50
        )
        return {
            "previous_result": previous_result,
            "after_wins": after_wins,
            "after_losses": after_losses,
            "samples": samples,
            "next_win_rate": next_win_rate,
            "dominant_rate": dominant_rate,
            "in_50_60_band": in_50_60_band,
            "priority": priority,
        }

    async def pair_transition_context(self, method: str, before: int, raw_stats: dict) -> dict:
        reset = int(await self.db.get("stats_reset_at", "0"))
        rows = await (await self.db.conn.execute("""
            SELECT result FROM (
                SELECT p.market_open_time, p.result
                FROM pair_predictions p
                JOIN pair_decisions d ON d.market_open_time=p.market_open_time
                WHERE p.method=?
                  AND json_extract(d.snapshot, '$.matching_rule')='wick_votes_v3'
                  AND p.market_open_time>=?
                  AND p.market_close_time<?
                  AND p.result IN ('WIN','LOSS')
                ORDER BY p.market_open_time DESC
                LIMIT ?
            ) recent
            ORDER BY market_open_time ASC
        """, (method, reset, before, STATS_WINDOW + 1))).fetchall()
        return self.priority_from_results(raw_stats, [row["result"] for row in rows])

    async def make_decision(self, open_time, delay):
        async with self._decision_send_lock:
            await asyncio.sleep(delay)
            try:
                await self._ensure_pair_schema()
                snapshot = await self._pair_decision(open_time)
                if snapshot is None:
                    live = self.live_m5
                    if live is None or live.open_time != open_time:
                        await self.rest_snapshot()
                        live = self.live_m5
                    if live is None or live.open_time != open_time:
                        self.last_decision_state = "KHÔNG MUA: THIẾU NẾN LIVE"
                        return
                    if await self._row_for_signal(open_time) is not None:
                        return

                    requested_method = await self.current_pair_method()
                    history = await self._closed_m5_history(open_time)
                    matches = find_pair_matches(history, open_time)
                    stats = await self.pair_stats(open_time)
                    selected = self.select_requested_method(matches, stats, requested_method)
                    if selected:
                        selected.update(await self.pair_transition_context(
                            requested_method, open_time, selected["raw_stats"]
                        ))

                    base = float(await self.db.get("base_bet", str(self.config.base_bet)))
                    step = int(await self.db.get("bet_step", "1"))
                    snapshot = {
                        "matching_rule": "wick_votes_v3",
                        "requested_method": requested_method,
                        "selected": selected,
                        "stats": stats,
                        "matches": {
                            method: match.to_dict() if match else None
                            for method, match in matches.items()
                        },
                        "close_time": live.close_time,
                        "target_price": live.open,
                        "signal_price": self.live_price if self.live_price > 0 else live.close,
                        "bet_step": step,
                        "bet_amount": min(base * (2 if step == 2 else 1), self.config.max_bet),
                        "actual": bool(await self.signals_enabled()),
                    }
                    try:
                        cursor = await self.db.conn.execute(
                            "INSERT OR IGNORE INTO pair_decisions VALUES(?,?)",
                            (open_time, json.dumps(snapshot)),
                        )
                        if cursor.rowcount:
                            rows = []
                            for method in METHODS:
                                match = matches.get(method)
                                rows.append((
                                    open_time, live.close_time, method,
                                    match.raw_direction if match else None,
                                    match.similarity if match else None,
                                    match.matched_open_time if match else None,
                                    match.matched_next_open_time if match else None,
                                ))
                            await self.db.conn.executemany(
                                "INSERT OR IGNORE INTO pair_predictions VALUES(?,?,?,?,?,?,?,NULL)",
                                rows,
                            )
                        await self.db.conn.commit()
                    except Exception:
                        await self.db.conn.rollback()
                        raise
                    snapshot = await self._pair_decision(open_time)

                selected = snapshot["selected"]
                if selected:
                    p = Prediction(
                        open_time, snapshot["close_time"], snapshot["target_price"],
                        snapshot["signal_price"], selected["direction"],
                        selected["effective_rate"], selected["match"]["similarity"],
                        selected["match"]["similarity"],
                        selected["match"].get("green_count", 0) + selected["match"].get("red_count", 0),
                        snapshot["bet_amount"], snapshot["bet_step"], snapshot["actual"],
                    )
                    await self.db.create_signal(p)
                    await self._ensure_primary_message(await self._row_for_signal(open_time))
                    await self._ensure_action_message(open_time)
                elif snapshot["actual"]:
                    method = snapshot.get("requested_method", "color_pair")
                    key = f"pair_no_buy:{open_time}"
                    if await self.db.get(key, "0") != "1" and await self._claim_signal_message(open_time):
                        try:
                            await self.telegram.send(
                                "⚠️ <b>KHÔNG NÊN VÀO LỆNH</b>\n"
                                f"Phương pháp đã chọn: <b>{METHOD_LABELS.get(method, method)}</b>.\n"
                                "Không có mẫu hợp lệ hoặc số nến xanh bằng đỏ trong 24 giờ."
                            )
                            await self.db.set(key, "1")
                            await self._mark_signal_sent(open_time)
                        except Exception:
                            await self._release_signal_claim(open_time)
                            raise
                self.last_decision_open = open_time
                self.last_decision_state = (
                    f"{METHOD_LABELS[selected['method']]} → {selected['direction']}"
                    if selected else "KHÔNG MUA"
                )
            except Exception as exc:
                self.last_decision_state = "LỖI BỘ CHỌN PHƯƠNG PHÁP"
                log.exception("Manual pair-method decision failed")
                await self.db.event("PAIR_DECISION_ERROR", {
                    "open_time": open_time, "error": str(exc),
                })
            finally:
                self.decision_tasks.pop(open_time, None)

    async def signal_text(self, p):
        snapshot = await self._pair_decision(p.market_open_time)
        if snapshot is None:
            return await super().signal_text(p)
        selected = snapshot["selected"]
        stats = selected["raw_stats"]
        local = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp((p.market_close_time + 1) / 1000, self.config.timezone)
        side = DIRECTION_LABELS[p.direction]
        icon = "🟢" if p.direction == "UP" else "🔴"
        totals = await self._entry_totals_since_reset()

        previous_result = selected.get("previous_result")
        if previous_result:
            previous_line = (
                f"↩️ Lệnh trước của phương pháp: <b>"
                f"{'✅ THẮNG' if previous_result == 'WIN' else '❌ THUA'}</b>"
            )
        else:
            previous_line = "↩️ Lệnh trước của phương pháp: <b>chưa có dữ liệu</b>"

        samples = int(selected.get("samples", 0))
        next_win_rate = selected.get("next_win_rate")
        if previous_result and samples and next_win_rate is not None:
            transition_line = (
                f"🔁 Sau {RESULT_LABELS[previous_result]}: ✅ {selected.get('after_wins', 0)} thắng • "
                f"❌ {selected.get('after_losses', 0)} thua → <b>{float(next_win_rate) * 100:.1f}% thắng</b>"
            )
        else:
            transition_line = "🔁 Chuỗi sau lệnh trước: chưa đủ dữ liệu"

        priority_line = ""
        if selected.get("priority"):
            priority_line = (
                "\n🔥 <b>ƯU TIÊN ĐÁNH</b>: phương pháp đang ở vùng 50–60% và "
                "lịch sử sau kết quả lệnh trước nghiêng về THẮNG."
            )

        return (
            f"{icon} <b>MUA {side}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {local:%H:%M}–{local_close:%H:%M}\n"
            f"🎯 Phương pháp: <b>{METHOD_LABELS[selected['method']]}</b>\n"
            f"🔎 Sau các cặp 24h: 🟢 {selected['match'].get('green_count', 0)} xanh • "
            f"🔴 {selected['match'].get('red_count', 0)} đỏ\n"
            f"🗳 Dùng kết quả chiếm đa số của phương pháp đã chọn\n"
            f"📊 Gốc: ✅ {stats['wins']} thắng • ❌ {stats['losses']} thua\n"
            f"{previous_line}\n"
            f"{transition_line}"
            f"{priority_line}\n"
            f"🏆 Lệnh thực tế: ✅ {totals['wins']} thắng • ❌ {totals['losses']} thua\n"
            f"💵 Giá: <code>{p.signal_price:,.2f}</code> • <b>LỆNH {p.bet_step}</b>: {p.bet_amount:.2f} USDT"
        )

    async def status_text(self):
        text = await super().status_text()
        method = await self.current_pair_method()
        lines = text.splitlines()
        lines.insert(1, f"🎯 Phương pháp gửi lệnh: <b>{METHOD_LABELS[method]}</b>")
        return "\n".join(lines)

    async def safe_startup_message(self):
        try:
            method = await self.current_pair_method()
            await self.telegram.send(
                f"<b>BOT V{APP_VERSION} ĐÃ CHẠY</b>\n"
                f"Phương pháp gửi lệnh hiện tại: <b>{METHOD_LABELS[method]}</b>.\n"
                "Bấm CHỌN PHƯƠNG PHÁP để đổi giữa Màu + loại râu và Thế nến.\n"
                "Hai phương pháp vẫn được chấm nền; chỉ phương pháp đã chọn được phép tạo lệnh Telegram.\n"
                "Với thống kê 50–60%, bot xét THẮNG/THUA của lệnh trước và báo ƯU TIÊN ĐÁNH khi chuỗi kế tiếp nghiêng về thắng.",
                enabled=await self.db.get("manual_enabled", "1") == "1",
            )
        except Exception as exc:
            self.telegram.last_error = str(exc)
            log.warning("Startup message failed: %s", exc)

    async def handle_telegram(self, kind, value, update):
        if kind == "callback" and value == "analysis_mode":
            await self.telegram.send_pair_method_menu(
                await self.current_pair_method(),
                await self.pair_stats(self.server_now_ms()),
            )
            return
        if kind == "callback" and value.startswith("mode_"):
            requested = value[5:]
            if requested in METHODS:
                selected = await self._set_pair_method(requested)
                await self.telegram.send(
                    f"✅ Đã chọn phương pháp gửi lệnh: <b>{METHOD_LABELS[selected]}</b>\n"
                    "Từ phiên 5 phút kế tiếp chỉ phương pháp này được dùng để tạo lệnh Telegram. "
                    "Phương pháp còn lại vẫn chạy nền để ghi thống kê."
                )
            else:
                await self.telegram.send(
                    "V3.8.0 chỉ cho chọn 1 trong 2 phương pháp: Màu + loại râu hoặc Thế nến."
                )
            return
        if kind == "message":
            command = value.split()[0].lower() if value.split() else ""
            if command in ("/mode", "/modes"):
                await self.telegram.send_pair_method_menu(
                    await self.current_pair_method(),
                    await self.pair_stats(self.server_now_ms()),
                )
                return
        await super().handle_telegram(kind, value, update)
