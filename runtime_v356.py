from __future__ import annotations

from datetime import datetime

import runtime_v355 as v355


APP_VERSION = "3.5.6"

# Keep only inherited base-runtime status text on the current visible version.
# Older runtime modules keep their frozen version constants for regression tests.
v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


class TradingSignalBotV3(v355.TradingSignalBotV3):
    """V3.5.6: clearer compact entry card with totals since the last stats reset."""

    async def _entry_totals_since_reset(self) -> dict[str, int]:
        reset_at = int(await self.db.get("stats_reset_at", "0"))
        row = await (await self.db.conn.execute(
            """SELECT
                   SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses
               FROM signals
               WHERE market_open_time>=? AND status='SETTLED' AND actual=1""",
            (max(0, reset_at),),
        )).fetchone()
        return {
            "wins": int(row["wins"] or 0),
            "losses": int(row["losses"] or 0),
        }

    async def signal_text(self, p) -> str:
        stats, _qualified = await self._signal_calibration(p)
        pairs = await self.pair_stats_since_reset()
        totals = await self._entry_totals_since_reset()

        local_open = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp((p.market_close_time + 1) / 1000, self.config.timezone)
        direction = "MUA TĂNG" if p.direction == "UP" else "MUA GIẢM"
        direction_icon = "🟢" if p.direction == "UP" else "🔴"

        if int(stats.get("decided", 0)) > 0:
            expected = float(stats.get("win_rate", 0.0))
        else:
            expected = float(p.confidence) * 100.0

        return (
            f"📥 <b>TÍN HIỆU M5</b>\n"
            f"{direction_icon} <b>{direction}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {local_open:%H:%M}–{local_close:%H:%M}\n"
            f"📊 Dự kiến thắng: <b>{expected:.1f}%</b>\n"
            f"📋 Tổng: ✅ {totals['wins']} thắng • ❌ {totals['losses']} thua\n"
            f"🔗 Cặp: ✅ {pairs['win_pairs']} thắng • ❌ {pairs['loss_pairs']} thua\n"
            f"💵 Giá: <code>{p.signal_price:,.2f}</code> • <b>LỆNH {p.bet_step}</b>: {p.bet_amount:.2f} USDT"
        )
