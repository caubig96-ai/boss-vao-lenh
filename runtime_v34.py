from __future__ import annotations

from datetime import datetime, timezone

import runtime_v33 as v33


APP_VERSION = "3.4.0"

# Keep inherited Telegram/status text on one visible version.
v33.APP_VERSION = APP_VERSION
v33.base_runtime.APP_VERSION = APP_VERSION


class TradingSignalBotV3(v33.TradingSignalBotV3):
    """V3.4: settle strictly by the final Binance M5 candle color.

    Prediction UP wins only when the official Binance M5 candle closes green
    (close > open). Prediction DOWN wins only when it closes red (close < open).
    A doji (close == open) is a tie. target_price is retained only for database
    compatibility/audit and never participates in WIN/LOSS scoring.
    """

    @staticmethod
    def candle_result(direction: str, open_price: float, close_price: float) -> str:
        if close_price == open_price:
            return "TIE"
        candle_direction = "UP" if close_price > open_price else "DOWN"
        return "WIN" if direction == candle_direction else "LOSS"

    @staticmethod
    def candle_color(open_price: float, close_price: float) -> str:
        if close_price > open_price:
            return "XANH"
        if close_price < open_price:
            return "ĐỎ"
        return "DOJI"

    async def _sync_official_open(self, open_time: int, open_price: float) -> None:
        """Store official Binance M5 open for audit/display only."""
        await self.db.conn.execute(
            "UPDATE signals SET target_price=? WHERE market_open_time=? AND status='PENDING'",
            (open_price, open_time),
        )
        await self.db.conn.execute(
            "UPDATE mode_signals SET target_price=? WHERE market_open_time=? AND status='PENDING'",
            (open_price, open_time),
        )
        await self.db.conn.commit()

    async def _settle_modes_by_candle(self, open_time: int, open_price: float, close_price: float) -> int:
        rows = await (await self.db.conn.execute(
            "SELECT mode,direction FROM mode_signals WHERE market_open_time=? AND status='PENDING'",
            (open_time,),
        )).fetchall()
        if not rows:
            return 0
        settled_at = datetime.now(timezone.utc).isoformat()
        updates = [
            (
                self.candle_result(row["direction"], open_price, close_price),
                close_price,
                settled_at,
                open_time,
                row["mode"],
            )
            for row in rows
        ]
        await self.db.conn.executemany(
            """UPDATE mode_signals
               SET status='SETTLED',result=?,close_price=?,settled_at=?
               WHERE market_open_time=? AND mode=?""",
            updates,
        )
        await self.db.conn.commit()
        return len(updates)

    async def _settle_row_by_candle(self, row, open_price: float, close_price: float) -> None:
        result = self.candle_result(row["direction"], open_price, close_price)
        payout = float(await self.db.get("payout_rate", str(self.config.payout_rate)))
        bet = float(row["bet_amount"])
        pnl = bet * payout if result == "WIN" else (-bet if result == "LOSS" else 0.0)
        await self.db.settle(
            int(row["market_open_time"]),
            result,
            close_price,
            pnl if row["actual"] else 0.0,
        )
        if row["actual"]:
            await self.apply_money_management(row, result, pnl)
            try:
                await self.telegram.send(
                    await self.result_text(row, close_price, result, pnl, open_price),
                    keyboard=False,
                )
            except Exception as exc:
                await self.db.event(
                    "RESULT_SEND_ERROR",
                    {"open_time": int(row["market_open_time"]), "error": str(exc)},
                )

    async def settle_market(self, candle) -> None:
        """Settle live WS/REST close using official M5 open+close, never target."""
        await self._sync_official_open(candle.open_time, candle.open)
        rows = [
            row for row in await self.db.pending()
            if int(row["market_open_time"]) == candle.open_time
        ]
        for row in rows:
            await self._settle_row_by_candle(row, candle.open, candle.close)
        await self._settle_modes_by_candle(candle.open_time, candle.open, candle.close)

    async def settle_pending(self) -> None:
        """Recover after restart using both official Binance M5 OPEN and CLOSE."""
        if not self.http:
            return
        now_ms = self.server_now_ms()
        selected = await self.db.pending()
        shadow = await self.db.pending_modes()

        sessions: dict[int, int] = {}
        for row in selected:
            sessions[int(row["market_open_time"])] = int(row["market_close_time"])
        for row in shadow:
            sessions[int(row["market_open_time"])] = int(row["market_close_time"])

        for open_time, close_time in sorted(sessions.items()):
            if close_time >= now_ms:
                continue
            params = {
                "symbol": self.config.symbol,
                "interval": "5m",
                "startTime": open_time,
                "limit": 1,
            }
            async with self.http.get(
                f"{v33.base_runtime.BINANCE_REST}/fapi/v1/klines",
                params=params,
            ) as response:
                response.raise_for_status()
                data = await response.json()
            if not data or int(data[0][0]) != open_time:
                continue

            official_open = float(data[0][1])
            official_close = float(data[0][4])
            await self._sync_official_open(open_time, official_open)

            current_selected = [
                row for row in await self.db.pending()
                if int(row["market_open_time"]) == open_time
            ]
            for row in current_selected:
                await self._settle_row_by_candle(row, official_open, official_close)
            await self._settle_modes_by_candle(open_time, official_open, official_close)

    async def pair_stats_since_reset(self) -> dict:
        """Count non-overlapping consecutive pairs: (1,2), (3,4), ...

        Only real/sent orders are counted. WIN+WIN is one win pair, LOSS+LOSS is
        one loss pair. Mixed results or a pair containing TIE are shown separately.
        """
        reset_at = int(await self.db.get("stats_reset_at", "0"))
        rows = await (await self.db.conn.execute(
            """SELECT result FROM signals
               WHERE market_open_time>=? AND status='SETTLED' AND actual=1
               ORDER BY market_open_time""",
            (max(0, reset_at),),
        )).fetchall()
        results = [row["result"] for row in rows]
        complete_pairs = len(results) // 2
        win_pairs = 0
        loss_pairs = 0
        other_pairs = 0
        for index in range(0, complete_pairs * 2, 2):
            first, second = results[index], results[index + 1]
            if first == second == "WIN":
                win_pairs += 1
            elif first == second == "LOSS":
                loss_pairs += 1
            else:
                other_pairs += 1
        return {
            "win_pairs": win_pairs,
            "loss_pairs": loss_pairs,
            "other_pairs": other_pairs,
            "complete_pairs": complete_pairs,
            "unpaired": len(results) % 2,
        }

    async def stats_text(self) -> str:
        text = await super().stats_text()
        pairs = await self.pair_stats_since_reset()
        return (
            text
            + "\n\n🔗 <b>CẶP 2 LỆNH LIÊN TIẾP</b>\n"
            + f"✅ Cặp thắng (THẮNG + THẮNG): <b>{pairs['win_pairs']}</b>\n"
            + f"❌ Cặp thua (THUA + THUA): <b>{pairs['loss_pairs']}</b>\n"
            + f"➖ Cặp khác/hòa: <b>{pairs['other_pairs']}</b>\n"
            + f"📦 Tổng cặp đã ghép: <b>{pairs['complete_pairs']}</b>"
            + (" | còn 1 lệnh lẻ" if pairs["unpaired"] else "")
        )

    async def signal_text(self, p) -> str:
        text = await super().signal_text(p)
        expected = "XANH (TĂNG)" if p.direction == "UP" else "ĐỎ (GIẢM)"
        old = f"🎯 Open/Target M5: <code>{p.target_price:,.2f}</code> USDT\n"
        new = (
            f"🎯 Kết quả cần: <b>NẾN M5 {expected}</b>\n"
            "🕯 Chấm kết quả chỉ theo màu nến Binance: TĂNG=xanh, GIẢM=đỏ; doji=hòa.\n"
        )
        return text.replace(old, new)

    async def result_text(
        self,
        row,
        close_price: float,
        result: str,
        pnl: float,
        open_price: float | None = None,
    ) -> str:
        official_open = float(open_price if open_price is not None else row["target_price"])
        direction = "TĂNG" if row["direction"] == "UP" else "GIẢM"
        color = self.candle_color(official_open, close_price)
        header = {
            "WIN": f"✅ <b>ĐÃ THẮNG {direction}</b>",
            "LOSS": f"❌ <b>ĐÃ THUA {direction}</b>",
            "TIE": f"➖ <b>ĐÃ HÒA {direction}</b>",
        }[result]
        difference = close_price - official_open
        return (
            f"{header}\n"
            f"🕯 Nến Binance M5: <b>{color}</b>\n"
            f"Open: <code>{official_open:,.2f}</code> USDT\n"
            f"Close: <code>{close_price:,.2f}</code> USDT\n"
            f"Chênh lệch: <code>{difference:+,.2f}</code> USDT\n"
            "📌 Quy tắc: dự đoán TĂNG thắng khi nến xanh; dự đoán GIẢM thắng khi nến đỏ; doji hòa."
        )
