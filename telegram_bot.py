from __future__ import annotations

import asyncio
import html
import logging

import aiohttp

log = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token: str, chat_id: str, handler):
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.handler = handler
        self.offset = 0
        self.session: aiohttp.ClientSession | None = None

    async def open(self) -> None:
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35))

    async def close(self) -> None:
        if self.session:
            await self.session.close()

    @staticmethod
    def keyboard() -> dict:
        return {"inline_keyboard": [
            [{"text": "🛑 DỪNG GỬI LỆNH", "callback_data": "stop"},
             {"text": "▶️ CHẠY LẠI", "callback_data": "start"}],
            [{"text": "📊 BÁO CÁO", "callback_data": "status"},
             {"text": "💵 ĐỔI VỐN", "callback_data": "setbet_help"}],
        ]}

    async def _call(self, method: str, payload: dict) -> dict:
        async with self.session.post(f"{self.base_url}/{method}", json=payload) as response:
            data = await response.json()
            if not response.ok or not data.get("ok"):
                raise RuntimeError(f"Telegram {method}: {data}")
            return data["result"]

    async def send(self, text: str, keyboard: bool = True) -> int:
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        if keyboard:
            payload["reply_markup"] = self.keyboard()
        result = await self._call("sendMessage", payload)
        return int(result["message_id"])

    async def edit(self, message_id: int, text: str) -> None:
        payload = {"chat_id": self.chat_id, "message_id": message_id, "text": text,
                   "parse_mode": "HTML", "reply_markup": self.keyboard()}
        try:
            await self._call("editMessageText", payload)
        except Exception as exc:
            log.warning("Không sửa được tin nhắn %s: %s", message_id, exc)

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        await self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def poll(self) -> None:
        while True:
            try:
                params = {"offset": self.offset + 1, "timeout": 25, "allowed_updates": ["message", "callback_query"]}
                async with self.session.get(f"{self.base_url}/getUpdates", params=params) as response:
                    data = await response.json()
                for update in data.get("result", []):
                    self.offset = max(self.offset, int(update["update_id"]))
                    await self._dispatch(update)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Telegram polling lỗi: %s", exc)
                await asyncio.sleep(3)

    async def _dispatch(self, update: dict) -> None:
        callback = update.get("callback_query")
        if callback:
            if str(callback.get("from", {}).get("id")) != self.chat_id:
                await self.answer_callback(callback["id"], "Không có quyền")
                return
            await self.handler("callback", callback.get("data", ""), callback)
            await self.answer_callback(callback["id"], "Đã xử lý")
            return
        message = update.get("message", {})
        if str(message.get("chat", {}).get("id")) != self.chat_id:
            return
        text = message.get("text", "").strip()
        if text:
            await self.handler("message", html.escape(text), message)

