import asyncio
from telegram_v3 import TelegramBot


def test_bot_constructs():
    bot = TelegramBot(token="", chat_id="")
    assert bot is not None
