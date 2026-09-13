from __future__ import annotations

import runtime_v376 as v376


APP_VERSION = "3.7.7"
log = v376.logging.getLogger("boss-vao-lenh-v377")

v376.v375.v374.v373.v372.v371.v37.v361.v36.v357.v356.v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


class TradingSignalBotV3(v376.TradingSignalBotV3):
    """V3.7.7: include exact 1/6 agreement win/loss history in cards and reports."""

    async def agreement_stats_since_reset(self) -> dict[int, dict[str, int | float]]:
        reset_at = int(await self.db.get("stats_reset_at", "0"))
        mode = await self.current_signal_mode()
        rows = await (await self.db.conn.execute(
            """SELECT agreement,
                      SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
                      SUM(CASE WHEN result='TIE' THEN 1 ELSE 0 END) AS ties
               FROM color_predictions
               WHERE status='SETTLED' AND market_open_time>=?
                 AND agreement BETWEEN 1 AND 6
                 AND COALESCE(signal_mode,'NORMAL')=?
               GROUP BY agreement""",
            (max(0, reset_at), mode),
        )).fetchall()
        result: dict[int, dict[str, int | float]] = {
            level: {"wins": 0, "losses": 0, "ties": 0, "decided": 0, "win_rate": 0.0}
            for level in range(1, 7)
        }
        for row in rows:
            level = int(row["agreement"])
            wins = int(row["wins"] or 0)
            losses = int(row["losses"] or 0)
            ties = int(row["ties"] or 0)
            result[level] = {
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "decided": wins + losses,
                "win_rate": v376.v375.v374._win_rate(wins, losses),
            }
        return result

    async def _one_of_six_line(self) -> str:
        exact = await self.agreement_stats_since_reset()
        return self._agreement_line(1, exact[1])

    async def signal_text(self, p) -> str:
        text = await super().signal_text(p)
        one = await self._one_of_six_line()
        # Parent releases render 2/6 first in both NORMAL and INVERSE history blocks.
        if "2/6:" in text and "1/6:" not in text:
            text = text.replace("2/6:", one + "\n2/6:", 1)
        return text

    async def threshold_stats_text(self) -> str:
        text = await super().threshold_stats_text()
        one = await self._one_of_six_line()
        if "2/6:" in text and "1/6:" not in text:
            text = text.replace("2/6:", one + "\n2/6:", 1)
        return text

    async def safe_startup_message(self) -> None:
        try:
            enabled = await self.db.get("manual_enabled", "1") == "1"
            mode = await self.current_signal_mode()
            self.telegram.inverse_enabled = mode == v376.v375.SIGNAL_MODE_INVERSE
            await self.telegram.send(
                f"🤖 <b>BOT V{APP_VERSION} ĐÃ CHẠY</b>\n"
                "🎨 COLOR ENGINE • 6 cách phân tích nến\n"
                "📚 Thống kê đồng thuận: <b>1/6 đến 6/6</b> thắng/thua/tỷ lệ\n"
                f"↔️ Chế độ: <b>{self.signal_mode_label(mode)}</b>",
                enabled=enabled,
            )
        except Exception as exc:
            self.telegram.last_error = str(exc)
            log.warning("Startup Telegram send failed: %s", exc)
