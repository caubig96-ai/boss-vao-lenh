from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import runtime_v377 as previous
import runtime_v3 as base_runtime
from models import Prediction
from pair_pattern_model import (
    HISTORY_CANDLES,
    METHODS,
    STATS_WINDOW,
    find_pair_matches,
    select_method,
    summarize,
)
from runtime_v375 import CompactTelegramBotV375


APP_VERSION = "3.7.9"
base_runtime.APP_VERSION = APP_VERSION
log = logging.getLogger("boss-two-pair-methods")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pair_predictions (
 market_open_time INTEGER NOT NULL, market_close_time INTEGER NOT NULL,
 method TEXT NOT NULL, raw_direction TEXT, similarity REAL,
 matched_open_time INTEGER, matched_next_open_time INTEGER, result TEXT,
 PRIMARY KEY(market_open_time, method)
);
CREATE INDEX IF NOT EXISTS pair_history ON pair_predictions(method, market_open_time);
CREATE TABLE IF NOT EXISTS pair_decisions (
 market_open_time INTEGER PRIMARY KEY, snapshot TEXT NOT NULL
);
"""

METHOD_LABELS = {
    "color_pair": "Màu + loại râu",
    "shape_pair": "Thế nến",
}
DIRECTION_LABELS = {"UP": "TĂNG", "DOWN": "GIẢM"}
RESULT_LABELS = {"WIN": "THẮNG", "LOSS": "THUA"}


class TwoMethodTelegram(CompactTelegramBotV375):
    """Only expose controls relevant to the active two-method engine."""

    def keyboard(self, enabled=None):
        base = super().keyboard(enabled)
        blocked = {"analysis_mode", "toggle_inverse_signal", "threshold_stats"}
        rows = []
        for row in base.get("inline_keyboard", []):
            filtered = [button for button in row if button.get("callback_data") not in blocked]
            if filtered:
                rows.append(filtered)
        # Put the two current reports directly below stop/start.
        insert_at = 1 if rows else 0
        rows[insert_at:insert_at] = [
            [{"text": "📈 2 PHƯƠNG PHÁP", "callback_data": "pair_stats"}],
            [{"text": "🏆 LỆNH THẮNG THỰC TẾ", "callback_data": "actual_wins"}],
        ]
        return {"inline_keyboard": rows}


class TradingSignalBotV3(previous.TradingSignalBotV3):
    """V3.7.9: color/wick successor majority."""

    def __init__(self, config):
        super().__init__(config)
        self.telegram = TwoMethodTelegram(
            config.telegram_token,
            config.telegram_chat_id,
            self.handle_telegram,
            self._save_telegram_offset,
        )

    async def _ensure_pair_schema(self):
        await self.db.conn.executescript(SCHEMA)
        await self.db.conn.commit()

    async def setup(self):
        await super().setup()
        await self._ensure_pair_schema()
        await self._recover_pairs()

    async def _recover_pairs(self):
        # Repair interrupted settlements only from an official closed Binance M5.
        await self.db.conn.execute("""
            UPDATE pair_predictions AS p SET result=(
              SELECT CASE WHEN p.raw_direction IS NULL THEN 'NEUTRAL'
                 WHEN (p.raw_direction='UP')=(c.close>=c.open) THEN 'WIN'
                 ELSE 'LOSS' END
              FROM candles c WHERE c.interval='5m' AND c.open_time=p.market_open_time)
            WHERE (result IS NULL OR result='TIE') AND EXISTS (
              SELECT 1 FROM candles c WHERE c.interval='5m' AND c.open_time=p.market_open_time)
        """)
        await self.db.conn.commit()

    async def settle_pending(self):
        await super().settle_pending()
        if self.db.conn:
            await self._ensure_pair_schema()
            await self._recover_pairs()

    async def settle_market(self, candle):
        if candle.interval != "5m" or not candle.closed:
            return
        await self._ensure_pair_schema()
        await self.db.conn.execute("""
            UPDATE pair_predictions SET result=CASE
              WHEN raw_direction IS NULL THEN 'NEUTRAL'
              WHEN (raw_direction='UP')=(?>=?) THEN 'WIN' ELSE 'LOSS' END
            WHERE market_open_time=? AND (result IS NULL OR result='TIE')
        """, (candle.close, candle.open, candle.open_time))
        await self.db.conn.commit()
        await super().settle_market(candle)

    @staticmethod
    def candle_result(direction, open_price, close_price):
        actual = "UP" if float(close_price) >= float(open_price) else "DOWN"
        return "WIN" if direction == actual else "LOSS"

    @staticmethod
    def candle_color(open_price, close_price):
        return "XANH" if float(close_price) >= float(open_price) else "ĐỎ"

    async def settle_row(self, row, close_price):
        """Override the legacy three-way scorer: every candle is WIN or LOSS."""
        target = float(row["target_price"])
        result = self.candle_result(row["direction"], target, close_price)
        payout = float(await self.db.get("payout_rate", str(self.config.payout_rate)))
        bet = float(row["bet_amount"])
        pnl = bet * payout if result == "WIN" else -bet
        await self.db.settle(
            int(row["market_open_time"]), result, close_price,
            pnl if row["actual"] else 0.0,
        )
        if row["actual"]:
            await self.apply_money_management(row, result, pnl)
            try:
                await self.telegram.send(
                    await self.result_text(row, close_price, result, pnl, target),
                    keyboard=False,
                )
            except Exception as exc:
                await self.db.event("RESULT_SEND_ERROR", {
                    "open_time": int(row["market_open_time"]), "error": str(exc),
                })

    async def pair_stats(self, before):
        reset = int(await self.db.get("stats_reset_at", "0"))
        stats = {}
        for method in METHODS:
            rows = await (await self.db.conn.execute("""
                SELECT p.result FROM pair_predictions p
                JOIN pair_decisions d ON d.market_open_time=p.market_open_time
                WHERE method=? AND json_extract(d.snapshot, '$.matching_rule')='wick_votes_v3'
                AND p.market_open_time>=? AND market_close_time<?
                AND result IN ('WIN','LOSS')
                ORDER BY p.market_open_time DESC LIMIT ?
            """, (method, reset, before, STATS_WINDOW))).fetchall()
            stats[method] = summarize(row["result"] for row in rows)
        return stats

    async def _pair_decision(self, open_time):
        row = await (await self.db.conn.execute(
            "SELECT snapshot FROM pair_decisions WHERE market_open_time=?", (open_time,),
        )).fetchone()
        return json.loads(row["snapshot"]) if row else None

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

                    history = await self._closed_m5_history(open_time)
                    matches = find_pair_matches(history, open_time)
                    stats = await self.pair_stats(open_time)
                    selected = select_method(matches, stats)
                    base = float(await self.db.get("base_bet", str(self.config.base_bet)))
                    step = int(await self.db.get("bet_step", "1"))
                    snapshot = {
                        "matching_rule": "wick_votes_v3",
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
                        selected["match"]["similarity"], selected["match"].get("green_count", 0) + selected["match"].get("red_count", 0),
                        snapshot["bet_amount"], snapshot["bet_step"], snapshot["actual"],
                    )
                    await self.db.create_signal(p)
                    await self._ensure_primary_message(await self._row_for_signal(open_time))
                    await self._ensure_action_message(open_time)
                elif snapshot["actual"]:
                    key = f"pair_no_buy:{open_time}"
                    if await self.db.get(key, "0") != "1" and await self._claim_signal_message(open_time):
                        try:
                            await self.telegram.send(
                                "⚠️ <b>KHÔNG NÊN VÀO LỆNH</b>\n"
                                "Cặp đúng màu + loại râu: không có mẫu hợp lệ hoặc số nến xanh bằng đỏ trong 24 giờ."
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
                self.last_decision_state = "LỖI BỘ CHỌN 2 PHƯƠNG PHÁP"
                log.exception("Pair decision failed")
                await self.db.event("PAIR_DECISION_ERROR", {
                    "open_time": open_time, "error": str(exc),
                })
            finally:
                self.decision_tasks.pop(open_time, None)

    @staticmethod
    def _pair_stats_text(stats):
        lines = ["<b>THỐNG KÊ GỐC 2 PHƯƠNG PHÁP</b>"]
        for method in METHODS:
            s = stats[method]
            lines.append(
                f"• {METHOD_LABELS[method]}: ✅ {s['wins']} thắng • ❌ {s['losses']} thua "
                f"• chỉ tham khảo"
            )
        return "\n".join(lines)

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
        return (
            f"{icon} <b>MUA {side}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {local:%H:%M}–{local_close:%H:%M}\n"
            f"🎯 Phương pháp: <b>{METHOD_LABELS[selected['method']]}</b>\n"
            f"🔎 Sau các cặp 24h: 🟢 {selected['match'].get('green_count', 0)} xanh • 🔴 {selected['match'].get('red_count', 0)} đỏ\n"
            f"🗳 Chọn màu chiếm đa số\n"
            f"📊 Gốc: ✅ {stats['wins']} thắng • ❌ {stats['losses']} thua\n"
            f"🏆 Lệnh thực tế: ✅ {totals['wins']} thắng • ❌ {totals['losses']} thua\n"
            f"💵 Giá: <code>{p.signal_price:,.2f}</code> • <b>LỆNH {p.bet_step}</b>: {p.bet_amount:.2f} USDT"
        )

    async def detail_signal_text(self, p):
        snapshot = await self._pair_decision(p.market_open_time)
        if snapshot is None:
            return await super().detail_signal_text(p)
        lines = [await self.signal_text(p), "", self._pair_stats_text(snapshot["stats"]), "", "<b>CẶP TÌM ĐƯỢC</b>"]
        for method in METHODS:
            match = snapshot["matches"].get(method)
            if match:
                lines.append(
                    f"• {METHOD_LABELS[method]}: {match.get('green_count', 0)} xanh / "
                    f"{match.get('red_count', 0)} đỏ → {DIRECTION_LABELS.get(match['raw_direction'], 'NGANG PHIẾU')}"
                )
            else:
                lines.append(f"• {METHOD_LABELS[method]}: không đạt điều kiện")
        return "\n".join(lines)

    async def result_text(self, row, close_price, result, pnl, open_price=None):
        official_open = float(open_price if open_price is not None else row["target_price"])
        direction = DIRECTION_LABELS[row["direction"]]
        header = f"✅ <b>ĐÃ THẮNG {direction}</b>" if result == "WIN" else f"❌ <b>ĐÃ THUA {direction}</b>"
        text = (
            f"{header}\n"
            f"🕯 Nến Binance M5: <b>{self.candle_color(official_open, close_price)}</b>\n"
            f"Open: <code>{official_open:,.2f}</code> USDT\n"
            f"Close: <code>{close_price:,.2f}</code> USDT\n"
            f"Chênh lệch: <code>{close_price - official_open:+,.2f}</code> USDT"
        )
        snapshot = await self._pair_decision(int(row["market_open_time"]))
        if snapshot and snapshot["selected"]:
            selected = snapshot["selected"]
            raw = ("LOSS" if result == "WIN" else "WIN") if selected["inverse"] else result
            text += (
                f"\n🎯 Phương pháp: <b>{METHOD_LABELS[selected['method']]}</b>"
                f"\n📊 Kết quả gốc: <b>{RESULT_LABELS[raw]}</b>"
                f"\n🏆 Kết quả lệnh thực tế: <b>{RESULT_LABELS[result]}</b>"
            )
        return text

    async def actual_wins_text(self):
        reset = int(await self.db.get("stats_reset_at", "0"))
        totals = await self.db.stats(reset, actual_only=True)
        rows = await (await self.db.conn.execute("""
            SELECT market_open_time,direction,bet_amount,pnl FROM signals
            WHERE actual=1 AND status='SETTLED' AND result='WIN' AND market_open_time>=?
            ORDER BY market_open_time DESC LIMIT 10
        """, (reset,))).fetchall()
        lines = [
            "🏆 <b>CÁC PHIÊN THẮNG THỰC TẾ</b>",
            f"Tổng: ✅ {totals['wins'] or 0} thắng • ❌ {totals['losses'] or 0} thua",
        ]
        if not rows:
            lines.append("Chưa có phiên thắng thực tế từ lần reset.")
        for row in rows:
            local = datetime.fromtimestamp(int(row["market_open_time"]) / 1000, self.config.timezone)
            lines.append(
                f"• {local:%d/%m %H:%M} • {DIRECTION_LABELS[row['direction']]} "
                f"• +{float(row['pnl']):.2f} USDT"
            )
        return "\n".join(lines)

    async def _signal_calibration(self, p):
        # The majority decision must also control the action message.
        snapshot = await self._pair_decision(p.market_open_time)
        return {"decided": 0, "win_rate": 0.0}, bool(snapshot and snapshot["selected"])

    async def threshold_stats_text(self):
        await self._ensure_pair_schema()
        return (
            self._pair_stats_text(await self.pair_stats(self.server_now_ms()))
            + f"\nDữ liệu dò: {HISTORY_CANDLES} nến M5 / 24 giờ."
            + "\nKhớp màu và loại râu từng nến; không xét độ dài thân/râu."
            + "\nĐếm tất cả nến sau cặp: xanh nhiều mua xanh, đỏ nhiều mua đỏ."
            + "\nNgang phiếu hoặc không có mẫu: không mua. Không tự đảo lệnh."
            + "\nThế nến chỉ thống kê loại râu để tham khảo."
        )

    async def stats_text(self):
        reset = int(await self.db.get("stats_reset_at", "0"))
        actual = await self.db.stats(reset, actual_only=True)
        virtual = await self.db.stats(reset, actual_only=False)
        balance = float(await self.db.get("current_balance", "0"))
        decided = int(virtual["wins"] or 0) + int(virtual["losses"] or 0)
        rate = int(virtual["wins"] or 0) / decided * 100 if decided else 0.0
        return (
            "\n\n📊 <b>THỐNG KÊ TỪ LẦN RESET</b>\n"
            f"🏆 Lệnh thực tế: ✅ {actual['wins'] or 0} thắng • ❌ {actual['losses'] or 0} thua\n"
            f"💵 Lãi/lỗ: <b>{actual['pnl']:+.2f} USDT</b> • Số dư: <b>{balance:.2f} USDT</b>\n"
            f"📡 Tất cả phân tích: ✅ {virtual['wins'] or 0} thắng • ❌ {virtual['losses'] or 0} thua • {rate:.1f}%\n\n"
            + await self.threshold_stats_text()
        )

    async def status_text(self):
        manual = await self.db.get("manual_enabled", "1") == "1"
        telegram_state = "CÓ LỖI" if self.telegram.last_error else "OK"
        return (
            f"<b>BOT V{APP_VERSION} • 2 PHƯƠNG PHÁP</b>\n"
            f"Gửi lệnh: <b>{'ĐANG CHẠY' if manual else 'ĐANG DỪNG'}</b>\n"
            f"Telegram: <b>{telegram_state}</b>\n"
            f"Giá BTC: <code>{self.live_price:,.2f}</code> USDT\n"
            f"Tạo lệnh: <b>{self.last_decision_state}</b>\n"
            + await self.stats_text()
        )

    async def safe_startup_message(self):
        try:
            await self.telegram.send(
                f"<b>BOT V{APP_VERSION} ĐÃ CHẠY</b>\n"
                "Quy tắc: ĐẾM CẶP MÀU + LOẠI RÂU (wick_votes_v3).\n"
                "Dò 24 giờ: khớp màu và râu trên/râu dưới/hai râu/không râu; bỏ độ dài thân/râu.\n"
                "Đếm nến sau mọi cặp phù hợp. Mua màu nhiều hơn; ngang phiếu thì không mua.",
                enabled=await self.db.get("manual_enabled", "1") == "1",
            )
        except Exception as exc:
            self.telegram.last_error = str(exc)
            log.warning("Startup message failed: %s", exc)

    async def handle_telegram(self, kind, value, update):
        if kind == "callback" and value == "stop":
            await self.db.set("manual_enabled", 0)
            await self.db.set("pause_started_at", self.server_now_ms())
            await self.telegram.send(
                "🔴 <b>ĐÃ DỪNG GỬI LỆNH</b>\nHai phương pháp vẫn tiếp tục phân tích và ghi thống kê gốc.",
                enabled=False,
            )
            return
        if kind == "callback" and value == "start":
            await self.db.set("manual_enabled", 1)
            await self.db.set("risk_pause_until", 0)
            await self.db.set("risk_cycle_losses", 0)
            await self.telegram.send("🟢 <b>BOT ĐANG CHẠY</b>" + await self.stats_text(), enabled=True)
            return
        if kind == "callback" and value in {"pair_stats", "threshold_stats"}:
            await self.telegram.send(await self.threshold_stats_text())
            return
        if kind == "callback" and value == "actual_wins":
            await self.telegram.send(await self.actual_wins_text())
            return
        if kind == "callback" and (value == "toggle_inverse_signal" or value == "analysis_mode" or value.startswith("mode_")):
            await self.telegram.send("V3.7.9 chỉ dùng Màu + loại râu và Thế nến; lệnh theo đa số cặp đúng màu + loại râu, không tự đảo.")
            return
        if kind == "message":
            command = value.split()[0].lower() if value.split() else ""
            if command in ("/thresholds", "/methods"):
                await self.telegram.send(await self.threshold_stats_text())
                return
            if command in ("/wins", "/actualwins"):
                await self.telegram.send(await self.actual_wins_text())
                return
            if command == "/help":
                await self.telegram.send(
                    "Lệnh: /status, /methods, /wins, /setbet 1, /setbalance 100, /setpayout 80"
                )
                return
            if command in ("/mode", "/modes"):
                await self.telegram.send("V3.7.9 chỉ có 2 phương pháp tự động: Màu + loại râu và Thế nến.")
                return
        await super().handle_telegram(kind, value, update)
