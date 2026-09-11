import asyncio
import unittest

from runtime_v354 import APP_VERSION, CompactTelegramBotV354


class TelegramControlsV354Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "3.5.4")

    def test_entry_adds_detail_without_removing_old_controls(self):
        async def scenario():
            bot = CompactTelegramBotV354("token", "1", None)
            bot.detail_open_time = 123456789
            calls = []

            async def fake_call(method, payload):
                calls.append((method, payload))
                return {"message_id": 88}

            bot._call = fake_call
            message_id = await bot.send("📥 <b>TÍN HIỆU M5</b>\n🟢 <b>MUA TĂNG</b>", enabled=True)
            self.assertEqual(message_id, 88)

            rows = calls[0][1]["reply_markup"]["inline_keyboard"]
            self.assertEqual(rows[0][0]["text"], "📋 CHI TIẾT")
            self.assertEqual(rows[0][0]["callback_data"], "detail_123456789")

            callbacks = [button["callback_data"] for row in rows[1:] for button in row]
            for expected in (
                "stop",
                "start",
                "status",
                "setbet_help",
                "analysis_mode",
                "threshold_stats",
                "reset_stats",
            ):
                self.assertIn(expected, callbacks)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
