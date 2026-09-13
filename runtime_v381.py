from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

import runtime_v3 as base_runtime
import runtime_v379 as legacy
import runtime_v380 as previous
from models import Prediction
from pair_pattern_model import (
    HISTORY_CANDLES,
    METHODS,
    STATS_WINDOW,
    find_nearest_pair_matches,
    summarize,
)


APP_VERSION = "3.8.1"
MATCHING_RULE = "nearest_pair_v4"
previous.APP_VERSION = APP_VERSION
legacy.APP_VERSION = APP_VERSION
base_runtime.APP_VERSION = APP_VERSION
log = logging.getLogger("boss-nearest-pair")

METHOD_LABELS = previous.METHOD_LABELS
DIRECTION_LABELS = previous.DIRECTION_LABELS
RESULT_LABELS = previous.RESULT_LABELS
TwoMethodTelegramV380 = previous.TwoMethodTelegramV380


class TradingSignalBotV3(previous.TradingSignalBotV3):
    """V3.8.1: selected method follows the closest matching historical candle pair."""

    @staticmethod
    def select_requested_method(matches, stats, method: str):
        if method not in METHODS:
            method = "color_pair"
        match = matches.get(method)
        if match is None or match.raw_direction is None:
            return None
        raw_stats = dict(stats[method])
        effective_rate = (
            float(raw_stats.get("win_rate", 0.5))
            if int(raw_stats.get("decided", 0)) > 0
            else 0.5
        )
        return {
            "method": method,
            "raw_direction": match.raw_direction,
            "direction": match.raw_direction,
            "inverse": False,
            "effective_rate": effective_rate,
            "match": match.to_dict(),
            "raw_stats": raw_stats,
        }

    async def pair_stats(self, before):
        reset = int(await self.db.get("stats_reset_at", "0"))
        stats = {}
        for method in METHODS:
            rows = await (await self.db.conn.execute("""
                SELECT p.result FROM pair_predictions p
                JOIN pair_decisions d ON d.market_open_time=p.market_open_time
                WHERE method=? AND json_extract(d.snapshot, '$.matching_rule')=?
                AND p.market_open_time>=? AND market_close_time<?
                AND result IN ('WIN','LOSS')
                ORDER BY p.market_open_time DESC LIMIT ?
            """, (method, MATCHING_RULE, reset, before, STATS_WINDOW))).fetchall()
            stats[method] = summarize(row["result"] for row in rows)
        return stats

    async def pair_transition_context(self, method: str, before: int, raw_stats: dict) -> dict:
        reset = int(await self.db.get("stats_reset_at", "0"))
        rows = await (await self.db.conn.execute("""
            SELECT result FROM (
                SELECT p.market_open_time, p.result
                FROM pair_predictions p
                JOIN pair_decisions d ON d.market_open_time=p.market_open_time
                WHERE p.method=?
                  AND json_extract(d.snapshot, '$.matching_rule')=?
                  AND p.market_open_time>=?
                  AND p.market_close_time<?
                  AND p.result IN ('WIN','LOSS')
                ORDER BY p.market_open_time DESC
                LIMIT ?
            ) recent
            ORDER BY market_open_time ASC
        """, (method, MATCHING_RULE, reset, before, STATS_WINDOW + 1))).fetchall()
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
                    matches = find_nearest_pair_matches(history, open_time)
                    stats = await self.pair_stats(open_time)
                    selected = self.select_requested_method(matches, stats, requested_method)
                    if selected:
                        selected.update(await self.pair_transition_context(
                            requested_method, open_time, selected["raw_stats"]
                        ))

                    base = float(await self.db.get("base_bet", str(self.config.base_bet)))
                    step = int(await self.db.get("bet_step", "1"))
                    snapshot = {
                        "matching_rule": MATCHING_RULE,
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
                                    open_time,
                                    live.close_time,
                                    method,
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
                        open_time,
                        snapshot["close_time"],
                        snapshot["target_price"],
                        snapshot["signal_price"],
                        selected["direction"],
                        selected["effective_rate"],
                        selected["match"]["similarity"],
                        selected["match"]["similarity"],
                        1,
                        snapshot["bet_amount"],
                        snapshot["bet_step"],
                        snapshot["actual"],
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
                                "Không tìm thấy cặp nến khớp gần nhất hợp lệ trong 24 giờ."
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
                self.last_decision_state = "LỖI CẶP NẾN GẦN NHẤT"
                log.exception("Nearest-pair decision failed")
                await self.db.event("PAIR_DECISION_ERROR", {
                    "open_time": open_time,
                    "error": str(exc),
                })
            finally:
                self.decision_tasks.pop(open_time, None)

    async def signal_text(self, p):
        text = await super().signal_text(p)
        snapshot = await self._pair_decision(p.market_open_time)
        if not snapshot or not snapshot.get("selected"):
            return text

        selected = snapshot["selected"]
        match = selected["match"]
        matched_open = int(match["matched_open_time"])
        matched_next = int(match["matched_next_open_time"])
        pair_start = datetime.fromtimestamp(matched_open / 1000, self.config.timezone)
        pair_end = datetime.fromtimestamp(matched_next / 1000, self.config.timezone)
        successor_side = DIRECTION_LABELS[selected["direction"]]
        successor_icon = "🟢" if selected["direction"] == "UP" else "🔴"

        lines = []
        for line in text.splitlines():
            if line.startswith("🔎 Sau các cặp 24h:"):
                lines.append(
                    f"🔎 Cặp nến gần nhất: <b>{pair_start:%H:%M}–{pair_end:%H:%M}</b>"
                )
                lines.append(
                    f"➡️ Nến ngay sau cặp đó: {successor_icon} <b>{successor_side}</b>"
                )
            elif line.startswith("🗳 Dùng kết quả chiếm đa số"):
                lines.append("🗳 Dùng kết quả của <b>cặp nến khớp gần nhất</b>, không lấy màu chiếm đa số")
            else:
                lines.append(line)
        return "\n".join(lines)

    async def threshold_stats_text(self):
        return (
            self._pair_stats_text(await self.pair_stats(self.server_now_ms()))
            + f"\nDữ liệu dò: {HISTORY_CANDLES} nến M5 / 24 giờ."
            + "\nTìm từ gần về xa và lấy cặp khớp gần nhất của phương pháp đã chọn."
            + "\nMàu của nến ngay sau cặp gần nhất quyết định TĂNG/GIẢM."
            + "\nKhông cộng phiếu và không lấy màu chiếm đa số của nhiều cặp."
            + "\nPhương pháp còn lại chỉ chạy nền để ghi thống kê."
        )

    async def safe_startup_message(self):
        try:
            method = await self.current_pair_method()
            await self.telegram.send(
                f"<b>BOT V{APP_VERSION} ĐÃ CHẠY</b>\n"
                f"Phương pháp gửi lệnh hiện tại: <b>{METHOD_LABELS[method]}</b>.\n"
                "Quy tắc mới: tìm cặp nến khớp gần nhất trong 24 giờ và lấy màu nến ngay sau cặp đó.\n"
                "Không còn chọn màu chiếm đa số của tất cả cặp.\n"
                "Với thống kê 50–60%, bot vẫn xét THẮNG/THUA lệnh trước để báo ƯU TIÊN ĐÁNH.",
                enabled=await self.db.get("manual_enabled", "1") == "1",
            )
        except Exception as exc:
            self.telegram.last_error = str(exc)
            log.warning("Startup message failed: %s", exc)
