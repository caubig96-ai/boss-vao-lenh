from __future__ import annotations

import logging

import runtime_v371 as v371


APP_VERSION = "3.7.2"
log = logging.getLogger("boss-vao-lenh-v372")

# Keep inherited visible version text current while preserving frozen release constants.
v371.v37.v361.v36.v357.v356.v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


class TradingSignalBotV3(v371.TradingSignalBotV3):
    """V3.7.2 keeps the single COLOR ENGINE and makes startup state explicit."""

    async def safe_startup_message(self) -> None:
        try:
            enabled = await self.db.get("manual_enabled", "1") == "1"
            await self.telegram.send(
                f"🤖 <b>BOT V{APP_VERSION} ĐÃ CHẠY</b>\n"
                "🎨 Chế độ duy nhất: <b>COLOR ENGINE</b>\n"
                "🧩 kNN + chuỗi màu + thân nến + Close + râu nến + regime\n"
                "🔒 Chỉ dùng nến M5 đã đóng để dự đoán XANH/ĐỎ.",
                enabled=enabled,
            )
        except Exception as exc:
            self.telegram.last_error = str(exc)
            log.warning("Startup Telegram send failed; market engine continues: %s", exc)
