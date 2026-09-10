from __future__ import annotations

import asyncio
import html
import logging
from collections.abc import Awaitable, Callable

import aiohttp

log = logging.getLogger(__name__)

OffsetSaver = Callable[[int], Awaitable[None]]


class TelegramBotV3:
    """Telegram client whose update offset survives restarts.

    Old versions restarted with offset=0, so Telegram could replay stale STOP/RESET
    callbacks after every rebuild. V3 persists the newest update id in SQLite.
    """

    def __init__(self, token: str, chat_id: str, handler, offset_saver: OffsetSaver | None = None):
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.handler = handler
        self.offset_saver = offset_saver
        self.offset = 0
        self.enabled = True
        self.session: aiohttp.ClientSession | None = None
        self.last_error = ""
        self.poll_conflict = False

    async def open(self) -> None:
        timeout = aiohttp.ClientTimeout(total=40, connect=10, sock_read=35)
        self.session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    def keyboard(self, enabled: bool | None = None) -> dict:
        if enabled is not None:
            self.enabled = enabled
        enabled = self.enabled
        stop_text = "🔴 ĐANG DỪNG" if enabled is False else "⚪ DỪNG GỬI LỆNH"
        start_text = "🟢 ĐANG CHẠY" if enabled is True else "⚪ CHẠY LẠI"
        return {"inline_keyboard": [
            [{"text": stop_text, "callback_data": "stop"},
             {"text": start_text, "callback_data": "start"}],
            [{"text": "📊 BÁO CÁO", "callback_data": "status"},
             {"text": "💵 ĐỔI VỐN", "callback_data": "setbet_help"}],
            [{"text": "♻️ RESET THỐNG KÊ", "callback_data": "reset_stats"}],
        ]}

    async def _call(self, method: str, payload: dict) -> dict:
        if not self.session:
            raise RuntimeError("Telegram session chưa mở")
        async with self.session.post(f"{self.base_url}/{method}", json=payload) as response:
            data = await response.json(content_type=None)
            if not response.ok or not data.get("ok"):
                raise RuntimeError(f"Telegram {method}: {data}")
            self.last_error = ""
            return data["result"]

    async def send(self, text: str, keyboard: bool = True, enabled: bool | None = None) -> int:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if keyboard:
            payload["reply_markup"] = self.keyboard(enabled)
        result = await self._call("sendMessage", payload)
        return int(result["message_id"])

    async def ask(self, text: str, placeholder: str = "Nhập số tiền USDT") -> int:
        result = await self._call("sendMessage", {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {
                "force_reply": True,
                "selective": True,
                "input_field_placeholder": placeholder,
            },
        })
        return int(result["message_id"])

    async def ask_reset_confirmation(self) -> int:
        result = await self._call("sendMessage", {
            "chat_id": self.chat_id,
            "text": (
                "⚠️ <b>XÁC NHẬN RESET THỐNG KÊ?</b>\n"
                "Thắng, thua, lãi/lỗ và số dư theo dõi sẽ về 0. "
                "Lịch sử nến vẫn được giữ."
            ),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[
                {"text": "✅ ĐỒNG Ý RESET", "callback_data": "reset_confirm"},
                {"text": "❎ HỦY", "callback_data": "reset_cancel"},
            ]]},
        })
        return int(result["message_id"])

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            await self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except Exception:
            log.exception("Không trả lời được callback Telegram")

    async def bootstrap_offset(self) -> int:
        """On the first V3 run, skip stale Telegram backlog instead of replaying old STOP/RESET."""
        if self.offset > 0 or not self.session:
            return self.offset
        params = {"offset": -1, "timeout": 0, "allowed_updates": ["message", "callback_query"]}
        try:
            async with self.session.get(f"{self.base_url}/getUpdates", params=params) as response:
                data = await response.json(content_type=None)
            if response.ok and data.get("ok") and data.get("result"):
                self.offset = max(int(item["update_id"]) for item in data["result"])
                if self.offset_saver:
                    await self.offset_saver(self.offset)
            self.last_error = ""
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("Không bootstrap được Telegram offset: %s", exc)
        return self.offset

    async def _save_offset(self) -> None:
        if self.offset_saver:
            await self.offset_saver(self.offset)

    async def poll(self) -> None:
        while True:
            try:
                if not self.session:
                    await asyncio.sleep(1)
                    continue
                params = {
                    "offset": self.offset + 1,
                    "timeout": 25,
                    "allowed_updates": ["message", "callback_query"],
                }
                async with self.session.get(f"{self.base_url}/getUpdates", params=params) as response:
                    data = await response.json(content_type=None)
                if not response.ok or not data.get("ok"):
                    description = str(data.get("description", data))
                    self.poll_conflict = response.status == 409 or "Conflict" in description
                    raise RuntimeError(description)
                self.poll_conflict = False
                self.last_error = ""
                for update in data.get("result", []):
                    update_id = int(update["update_id"])
                    self.offset = max(self.offset, update_id)
                    await self._save_offset()
                    await self._dispatch(update)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                log.warning("Telegram polling lỗi: %s", exc)
                await asyncio.sleep(3)

    async def _dispatch(self, update: dict) -> None:
        callback = update.get("callback_query")
        if callback:
            if str(callback.get("from", {}).get("id")) != self.chat_id:
                await self.answer_callback(callback.get("id", ""), "Không có quyền")
                return
            await self.handler("callback", callback.get("data", ""), update)
            await self.answer_callback(callback.get("id", ""), "Đã xử lý")
            return
        message = update.get("message", {})
        if str(message.get("chat", {}).get("id")) != self.chat_id:
            return
        text = message.get("text", "").strip()
        if text:
            await self.handler("message", html.escape(text), update)
