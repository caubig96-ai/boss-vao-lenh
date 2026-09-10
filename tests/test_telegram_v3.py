import asyncio
import unittest

from telegram_v3 import TelegramBotV3


class TelegramV3Tests(unittest.TestCase):
    def test_offset_saver_is_called(self):
        saved = []

        async def saver(value: int):
            saved.append(value)

        async def scenario():
            bot = TelegramBotV3("token", "1", lambda *args: None, saver)
            bot.offset = 321
            await bot._save_offset()

        asyncio.run(scenario())
        self.assertEqual(saved, [321])


if __name__ == "__main__":
    unittest.main()
