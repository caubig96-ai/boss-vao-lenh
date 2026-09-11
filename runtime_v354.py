from __future__ import annotations

import runtime_v353 as v353


APP_VERSION = "3.5.4"

# Keep inherited visible version strings in sync.
v353.APP_VERSION = APP_VERSION
v353.v352.v351.v35.v34.v33.APP_VERSION = APP_VERSION
v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


class CompactTelegramBotV354(v353.CompactTelegramBotV353):
    """Entry card keeps every old control row and adds CHI TIẾT on top."""

    async def send(self, text: str, keyboard: bool = True, enabled: bool | None = None) -> int:
        if enabled is not None:
            self.enabled = enabled

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        if self.detail_open_time is not None and "TÍN HIỆU M5" in text:
            old_rows = self.keyboard(enabled)["inline_keyboard"]
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": "📋 CHI TIẾT", "callback_data": f"detail_{self.detail_open_time}"}],
                    *old_rows,
                ]
            }
        elif keyboard:
            payload["reply_markup"] = self.keyboard(enabled)

        result = await self._call("sendMessage", payload)
        return int(result["message_id"])


class TradingSignalBotV3(v353.TradingSignalBotV3):
    """V3.5.4: same V3.5.3 messages, with all previous Telegram buttons restored."""

    def __init__(self, config):
        super().__init__(config)
        self.telegram = CompactTelegramBotV354(
            config.telegram_token,
            config.telegram_chat_id,
            self.handle_telegram,
            self._save_telegram_offset,
        )
