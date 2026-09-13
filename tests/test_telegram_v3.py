from telegram_v3 import TelegramBot


def test_init():
    assert TelegramBot(token="", chat_id="")
