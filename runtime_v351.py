from __future__ import annotations

import runtime_v35 as v35


APP_VERSION = "3.5.1"

# Keep all inherited status/Telegram version strings synchronized.
v35.APP_VERSION = APP_VERSION
v35.v34.APP_VERSION = APP_VERSION
v35.v34.v33.APP_VERSION = APP_VERSION
v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


class TradingSignalBotV3(v35.TradingSignalBotV3):
    """V3.5.1: always send the selected M5 signal while calibration controls advice.

    V3.3 used empirical calibration as a hard Telegram gate. In this version the
    selected mode is still reported every M5 session whenever normal sending is
    enabled. Calibration is advisory only:

    - qualified (enough samples + historical WR threshold): recommend entry and
      the existing calibrated Telegram helper sends the extra MUA TANG/GIAM NGAY.
    - not qualified: send the normal signal, clearly marked KHONG KHUYEN KHICH.

    Manual stop / risk pause still suppress sending exactly as before.
    """

    async def make_decision(self, open_time: int, delay: float) -> None:
        # Let V3.5 create the prediction, shadow rows and (for qualified setups)
        # send the normal Telegram signal using the existing calibrated path.
        await super().make_decision(open_time, delay)

        row = await self._row_for_signal(open_time)
        if row is None:
            return

        # If the row is already actual, the inherited path already sent it (or
        # left it in the retry outbox after a Telegram error). Just improve the
        # visible diagnostic state.
        if bool(row["actual"]):
            mode = await self.current_analysis_mode()
            stats = await v35.v34.v33.calibration_stats(self.db, mode, float(row["confidence"]))
            _, _, qualified = v35.v34.v33.calibration_quality(stats)
            if row["telegram_message_id"] is not None:
                self.last_decision_state = (
                    "ĐÃ GỬI TELEGRAM - KHUYẾN KHÍCH"
                    if qualified
                    else "ĐÃ GỬI TELEGRAM - KHÔNG KHUYẾN KHÍCH"
                )
            return

        # V3.3 writes BỎ QUA only when manual/risk sending was allowed but the
        # calibration threshold was not met. Promote exactly those rows to a
        # normal informational signal. Do NOT bypass manual stop or risk pause.
        if not self.last_decision_state.startswith("BỎ QUA:"):
            return

        await self.db.conn.execute(
            "UPDATE signals SET actual=1 WHERE market_open_time=?",
            (open_time,),
        )
        await self.db.conn.commit()
        row = await self._row_for_signal(open_time)
        if row is None:
            return

        try:
            message_id = await self.telegram.send(
                await self.signal_text(self._prediction_from_row(row)),
                enabled=True,
            )
            await self.db.update_message_id(open_time, message_id)
            self.last_decision_state = "ĐÃ GỬI TELEGRAM - KHÔNG KHUYẾN KHÍCH"
            await self.db.event(
                "SIGNAL_SENT_ADVISORY_ONLY",
                {
                    "open_time": open_time,
                    "reason": "calibration_not_qualified",
                },
            )
        except Exception as exc:
            # actual=1 keeps the normal outbox retry behavior intact.
            self.last_decision_state = "ĐÃ TẠO - CHỜ GỬI LẠI TELE"
            await self.db.event(
                "SIGNAL_SEND_ERROR",
                {"open_time": open_time, "error": str(exc)},
            )

    async def signal_text(self, p) -> str:
        text = await super().signal_text(p)
        mode = await self.current_analysis_mode()
        stats = await v35.v34.v33.calibration_stats(self.db, mode, p.confidence)
        _, _, qualified = v35.v34.v33.calibration_quality(stats)
        if qualified:
            advice = (
                "\n\n✅ <b>KHUYẾN KHÍCH VÀO LỆNH</b>\n"
                "Tín hiệu đã đạt điều kiện hiệu chỉnh lịch sử; bot sẽ gửi thêm cảnh báo MUA TĂNG/GIẢM NGAY."
            )
        else:
            advice = (
                "\n\n⚠️ <b>KHÔNG KHUYẾN KHÍCH VÀO LỆNH</b>\n"
                "Tín hiệu vẫn được gửi để theo dõi, nhưng chưa đạt điều kiện hiệu chỉnh lịch sử."
            )
        return text + advice

    async def threshold_stats_text(self) -> str:
        text = await super().threshold_stats_text()
        old = (
            "Score mô hình không phải xác suất thắng. Lệnh thực tế chỉ gửi khi đúng vùng score có ít nhất "
        )
        new = (
            "Score mô hình không phải xác suất thắng. Mọi tín hiệu M5 vẫn được gửi; chỉ KHUYẾN KHÍCH vào lệnh "
            "và gửi MUA TĂNG/GIẢM NGAY khi đúng vùng score có ít nhất "
        )
        return text.replace(old, new)
