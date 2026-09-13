from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

import runtime_v377 as previous
import runtime_v3 as base_runtime
from candle_color_model import predict_next_color
from component_selector import METHODS, WINDOW, MIN_SAMPLES, raw_direction, summarize, select_method
from models import Prediction
from runtime_v375 import CompactTelegramBotV375

APP_VERSION = "3.7.8"
base_runtime.APP_VERSION = APP_VERSION
log = logging.getLogger("boss-component-selector")
SCHEMA = """
CREATE TABLE IF NOT EXISTS component_predictions (
 market_open_time INTEGER NOT NULL, market_close_time INTEGER NOT NULL,
 method TEXT NOT NULL, probability REAL, raw_direction TEXT,
 result TEXT, PRIMARY KEY(market_open_time, method)
);
CREATE INDEX IF NOT EXISTS component_history ON component_predictions(method, market_open_time);
CREATE TABLE IF NOT EXISTS component_decisions (
 market_open_time INTEGER PRIMARY KEY, snapshot TEXT NOT NULL
);
"""

METHOD_LABELS = {
    "knn": "kNN mẫu tương tự",
    "sequence": "Chuỗi màu",
    "body": "Thân nến",
    "close_position": "Vị trí Close",
    "wick": "Áp lực râu nến",
    "regime": "Regime / cấu trúc",
}
RESULT_LABELS = {"WIN": "THẮNG", "LOSS": "THUA", "TIE": "HÒA", None: "--"}
DIRECTION_LABELS = {"UP": "TĂNG", "DOWN": "GIẢM"}


class SelectorTelegram(CompactTelegramBotV375):
    def keyboard(self, enabled=None):
        keyboard = super().keyboard(enabled)
        keyboard["inline_keyboard"] = [
            [b for b in row if b.get("callback_data") != "toggle_inverse_signal"]
            for row in keyboard["inline_keyboard"]
        ]
        keyboard["inline_keyboard"] = [row for row in keyboard["inline_keyboard"] if row]
        return keyboard


class TradingSignalBotV3(previous.TradingSignalBotV3):
    """Six unchanged forecasts; raw method ledger is separate from signals."""

    def __init__(self, config):
        super().__init__(config)
        self.telegram = SelectorTelegram(config.telegram_token, config.telegram_chat_id,
                                         self.handle_telegram, self._save_telegram_offset)

    async def _ensure_component_schema(self):
        await self.db.conn.executescript(SCHEMA)
        await self.db.conn.commit()

    async def setup(self):
        await super().setup()
        await self._ensure_component_schema()
        await self._recover_components()

    async def _recover_components(self):
        # Only official CLOSED candles in the DB are eligible for recovery.
        await self.db.conn.execute("""
            UPDATE component_predictions AS p SET result=(
              SELECT CASE WHEN p.raw_direction IS NULL THEN 'NEUTRAL'
                 WHEN c.close=c.open THEN 'TIE'
                 WHEN (p.raw_direction='UP')=(c.close>c.open) THEN 'WIN'
                 ELSE 'LOSS' END
              FROM candles c WHERE c.interval='5m' AND c.open_time=p.market_open_time)
            WHERE result IS NULL AND EXISTS (
              SELECT 1 FROM candles c WHERE c.interval='5m' AND c.open_time=p.market_open_time)
        """)
        await self.db.conn.commit()

    async def settle_pending(self):
        await super().settle_pending()
        if self.db.conn:
            await self._ensure_component_schema()
            await self._recover_components()

    async def settle_market(self, candle):
        if candle.interval != "5m" or not candle.closed:
            return
        await self._ensure_component_schema()
        await self.db.conn.execute("""
            UPDATE component_predictions SET result=CASE
              WHEN raw_direction IS NULL THEN 'NEUTRAL'
              WHEN ?=? THEN 'TIE'
              WHEN (raw_direction='UP')=(?>?) THEN 'WIN' ELSE 'LOSS' END
            WHERE market_open_time=? AND result IS NULL
        """, (candle.close, candle.open, candle.close, candle.open, candle.open_time))
        await self.db.conn.commit()
        await super().settle_market(candle)

    async def component_stats(self, before):
        reset = int(await self.db.get("stats_reset_at", "0"))
        stats = {}
        for method in METHODS:
            rows = await (await self.db.conn.execute("""
                SELECT result FROM component_predictions WHERE method=?
                AND market_open_time>=? AND market_close_time<?
                AND result IN ('WIN','LOSS','TIE')
                ORDER BY market_open_time DESC LIMIT ?
            """, (method, reset, before, WINDOW))).fetchall()
            stats[method] = summarize(row["result"] for row in rows)
        return stats

    async def _decision(self, open_time):
        row = await (await self.db.conn.execute(
            "SELECT snapshot FROM component_decisions WHERE market_open_time=?", (open_time,))).fetchone()
        return json.loads(row["snapshot"]) if row else None

    async def make_decision(self, open_time, delay):
        async with self._decision_send_lock:
            await asyncio.sleep(delay)
            try:
                await self._ensure_component_schema()
                snapshot = await self._decision(open_time)
                if snapshot is None:
                    live = self.live_m5
                    if live is None or live.open_time != open_time:
                        await self.rest_snapshot()
                        live = self.live_m5
                    if live is None or live.open_time != open_time:
                        self.last_decision_state = "KHÔNG MUA: THIẾU NẾN LIVE"
                        return
                    # Never take ownership of a session created by an older runtime.
                    if await self._row_for_signal(open_time) is not None:
                        return
                    await self._recover_components()
                    forecast = predict_next_color(await self._closed_m5_history(open_time))
                    stats = await self.component_stats(open_time)
                    selected = select_method(forecast.components, stats)
                    base = float(await self.db.get("base_bet", str(self.config.base_bet)))
                    step = int(await self.db.get("bet_step", "1"))
                    snapshot = dict(selected=selected, stats=stats, components=forecast.components,
                                    close_time=live.close_time, target_price=live.open,
                                    signal_price=self.live_price if self.live_price > 0 else live.close,
                                    bet_step=step, bet_amount=min(base * (2 if step == 2 else 1), self.config.max_bet),
                                    actual=bool(await self.signals_enabled()))
                    # Snapshot and six raw forecasts are committed together. Replays never recompute.
                    try:
                        cursor = await self.db.conn.execute(
                            "INSERT OR IGNORE INTO component_decisions VALUES(?,?)",
                            (open_time, json.dumps(snapshot)))
                        if cursor.rowcount:
                            await self.db.conn.executemany(
                                "INSERT OR IGNORE INTO component_predictions VALUES(?,?,?,?,?,NULL)",
                                [(open_time, live.close_time, m, forecast.components.get(m),
                                  raw_direction(forecast.components.get(m))) for m in METHODS])
                        await self.db.conn.commit()
                    except Exception:
                        await self.db.conn.rollback()
                        raise
                    snapshot = await self._decision(open_time)
                selected = snapshot["selected"]
                if selected:
                    p = Prediction(open_time, snapshot["close_time"], snapshot["target_price"],
                                   snapshot["signal_price"], selected["direction"], selected["ranking_rate"],
                                   .5, .5, selected["raw_stats"]["decided"], snapshot["bet_amount"],
                                   snapshot["bet_step"], snapshot["actual"])
                    await self.db.create_signal(p)
                    await self._ensure_primary_message(await self._row_for_signal(open_time))
                    await self._ensure_action_message(open_time)
                elif snapshot["actual"]:
                    # No fake selected trade, PnL or stake progression for NO BUY sessions.
                    key = f"component_no_buy:{open_time}"
                    if await self.db.get(key, "0") != "1" and await self._claim_signal_message(open_time):
                        try:
                            counts = [s["decided"] for s in snapshot["stats"].values()]
                            await self.telegram.send(
                                "⚠️ <b>KHÔNG NÊN VÀO LỆNH</b>\n"
                                "Chưa có phương pháp phù hợp với điều kiện lựa chọn.\n"
                                f"📊 Mẫu đã chấm: <b>{min(counts) if counts else 0}/{MIN_SAMPLES}</b> tối thiểu\n"
                                "📋 Bấm <b>TỶ LỆ NGƯỠNG</b> để xem thống kê 6 phương pháp."
                            )
                            await self.db.set(key, "1")
                            await self._mark_signal_sent(open_time)
                        except Exception:
                            await self._release_signal_claim(open_time)
                            raise
                self.last_decision_open = open_time
                self.last_decision_state = (f"{selected['method']} → {selected['direction']}"
                                            if selected else "KHÔNG MUA")
            except Exception as exc:
                self.last_decision_state = "LỖI BỘ CHỌN 6 PHƯƠNG PHÁP"
                log.exception("Component decision failed")
                await self.db.event("COMPONENT_DECISION_ERROR", {"open_time": open_time, "error": str(exc)})
            finally:
                self.decision_tasks.pop(open_time, None)

    @staticmethod
    def _stats_text(stats):
        lines = ["<b>THỐNG KÊ GỐC — KHÔNG ĐẢO KẾT QUẢ</b>"]
        for method in METHODS:
            s = stats[method]
            lines.append(f"{METHOD_LABELS[method]}: ✅ {s['wins']} thắng • ❌ {s['losses']} thua"
                         f" • ➖ {s['ties']} hòa • <b>{s['win_rate']:.1%}</b> thắng"
                         f" • gần nhất {RESULT_LABELS.get(s['last'], '--')}")
        return "\n".join(lines)

    async def signal_text(self, p):
        snapshot = await self._decision(p.market_open_time)
        if snapshot is None:
            return await super().signal_text(p)
        s = snapshot["selected"]
        side = "TĂNG" if p.direction == "UP" else "GIẢM"
        icon = "🟢" if p.direction == "UP" else "🔴"
        local = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp((p.market_close_time + 1) / 1000, self.config.timezone)
        stats = s["raw_stats"]
        totals = await self._entry_totals_since_reset()
        pairs = await self.pair_stats_since_reset()
        handling = "ĐẢO HƯỚNG" if s["inverse"] else "GIỮ HƯỚNG GỐC"
        rate_label = "tỷ lệ thua" if s["inverse"] else "tỷ lệ thắng"
        return (
            f"{icon} <b>MUA {side}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {local:%H:%M}–{local_close:%H:%M}\n"
            f"🎯 Phương pháp: <b>{METHOD_LABELS[s['method']]}</b>\n"
            f"↔️ Xử lý: <b>{handling}</b>\n"
            f"📊 Lịch sử gốc: ✅ {stats['wins']} thắng • ❌ {stats['losses']} thua • {rate_label} <b>{s['ranking_rate']:.1%}</b>\n"
            f"📋 Tổng lệnh gửi: ✅ {totals['wins']} thắng • ❌ {totals['losses']} thua\n"
            f"🔗 Cặp: ✅ {pairs['win_pairs']} thắng • ❌ {pairs['loss_pairs']} thua\n"
            f"💵 Giá: <code>{p.signal_price:,.2f}</code> • <b>LỆNH {p.bet_step}</b>: {p.bet_amount:.2f} USDT"
        )

    async def detail_signal_text(self, p):
        snapshot = await self._decision(p.market_open_time)
        if snapshot is None:
            return await super().detail_signal_text(p)
        return await self.signal_text(p) + "\n\n" + self._stats_text(snapshot["stats"])

    async def result_text(self, row, close_price, result, pnl, open_price=None):
        text = await super().result_text(row, close_price, result, pnl, open_price)
        snapshot = await self._decision(int(row["market_open_time"]))
        if snapshot and snapshot["selected"]:
            selected = snapshot["selected"]
            raw = ('LOSS' if result == 'WIN' else 'WIN') if selected['inverse'] and result != 'TIE' else result
            text += (f"\n🎯 Phương pháp: <b>{METHOD_LABELS[selected['method']]}</b>"
                     f"\n📊 Kết quả công thức gốc: <b>{RESULT_LABELS[raw]}</b>"
                     f"\n↔️ Kết quả lệnh gửi: <b>{RESULT_LABELS[result]}</b>")
        return text

    async def _signal_calibration(self, p):
        snapshot = await self._decision(p.market_open_time)
        if snapshot is None:
            return await super()._signal_calibration(p)
        return {"decided": 0, "win_rate": 0.0}, snapshot["selected"] is not None

    async def threshold_stats_text(self):
        await self._ensure_component_schema()
        return (self._stats_text(await self.component_stats(self.server_now_ms()))
                + f"\nCửa sổ {WINDOW} dự báo đã chấm; tối thiểu {MIN_SAMPLES} thắng/thua."
                + "\nThắng nhiều: giữ hướng. Thua nhiều: đảo hướng gửi, không đảo thống kê."
                + "\nChỉ xét khi hướng sử dụng vừa thua; 50/50 giữ gốc nếu gốc vừa thua.")

    async def status_text(self):
        return f"<b>BOT V{APP_VERSION} • 6 PHƯƠNG PHÁP ĐỘC LẬP</b>\n" + await self.threshold_stats_text()

    async def safe_startup_message(self):
        try:
            await self.telegram.send(f"<b>BOT V{APP_VERSION} ĐÃ CHẠY</b>\n"
                                     "6 phương pháp độc lập; bỏ ngưỡng đồng thuận X/6.\n"
                                     "Thống kê phương pháp luôn theo hướng gốc; lệnh gửi chấm riêng.",
                                     enabled=await self.db.get("manual_enabled", "1") == "1")
        except Exception as exc:
            self.telegram.last_error = str(exc)
            log.warning("Startup message failed: %s", exc)

    async def handle_telegram(self, kind, value, update):
        if kind == "callback" and value == "toggle_inverse_signal":
            await self.telegram.send("Bộ chọn 6 phương pháp tự chọn giữ/đảo từng phương pháp; nút đảo toàn bộ cũ đã tắt.")
            return
        await super().handle_telegram(kind, value, update)
