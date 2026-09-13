from __future__ import annotations

import aiohttp

from config import settings


class TelegramBot:
    def __init__(self, token=None, chat_id=None):
        self.token = token if token is not None else settings.telegram_bot_token
        self.chat_id = chat_id if chat_id is not None else settings.telegram_chat_id

    async def _send(self, text):
        if not self.token or not self.chat_id:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"chat_id": self.chat_id, "text": text}) as resp:
                return 200 <= resp.status < 300

    async def send_startup(self, version):
        return await self._send(
            f"🤖 BOSS VÀO LỆNH {version}\n"
            f"✅ Tool đã khởi động\n"
            f"📡 Đang chờ tín hiệu M5"
        )

    async def send_signal(self, signal, version=None):
        direction = signal.get("sent_direction") or signal.get("direction")
        arrow = "🟢 TĂNG" if direction == "UP" else "🔴 GIẢM"
        raw = signal.get("raw_direction")
        inverted = signal.get("inverted", False)
        mode = "ĐẢO LỆNH" if inverted else "GIỮ HƯỚNG"
        method = signal.get("method", "--")
        confidence = float(signal.get("confidence", 0) or 0) * 100
        wins = signal.get("wins", 0)
        losses = signal.get("losses", 0)
        text = (
            f"🚨 BOSS VÀO LỆNH{(' ' + version) if version else ''}\n"
            f"━━━━━━━━━━━━━━\n"
            f"📌 LỆNH: {arrow}\n"
            f"🧠 PP: {method}\n"
            f"🎯 Tin cậy: {confidence:.1f}%\n"
            f"📊 Gốc: {wins} THẮNG | {losses} THUA\n"
            f"🔁 Xử lý: {mode}"
        )
        if raw and raw != direction:
            text += f"\n↪️ Hướng gốc: {'TĂNG' if raw == 'UP' else 'GIẢM'}"
        return await self._send(text)
