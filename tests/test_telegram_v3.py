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

    def test_high_confidence_up_gets_instant_followup(self):
        text = (
            "📥 <b>TIN NHẮN VÀO LỆNH • V3.0.0</b>\n"
            "<b>🟢 𝗠𝗨𝗔 𝗧Ă𝗡𝗚: 1.00 USDT</b>\n"
            "🟢 <b>ĐỘ TIN CẬY: CAO – 71.2%</b>"
        )
        self.assertEqual(
            TelegramBotV3.instant_followup_text(text),
            "🚨 <b>MUA TĂNG NGAY</b>",
        )

    def test_high_confidence_down_gets_instant_followup(self):
        text = (
            "📥 <b>TIN NHẮN VÀO LỆNH • V3.0.0</b>\n"
            "<b>🔴 𝗠𝗨𝗔 𝗚𝗜Ả𝗠: 1.00 USDT</b>\n"
            "🟢 <b>ĐỘ TIN CẬY: CAO – 68.4%</b>"
        )
        self.assertEqual(
            TelegramBotV3.instant_followup_text(text),
            "🚨 <b>MUA GIẢM NGAY</b>",
        )

    def test_medium_or_low_signal_does_not_get_extra_message(self):
        text = (
            "📥 <b>TIN NHẮN VÀO LỆNH • V3.0.0</b>\n"
            "<b>🟢 𝗠𝗨𝗔 𝗧Ă𝗡𝗚: 1.00 USDT</b>\n"
            "🟡 <b>ĐỘ TIN CẬY: TRUNG BÌNH – 61.0%</b>"
        )
        self.assertIsNone(TelegramBotV3.instant_followup_text(text))

    def test_normal_signal_is_sent_before_high_confidence_followup(self):
        calls = []

        async def scenario():
            bot = TelegramBotV3("token", "1", lambda *args: None)

            async def fake_call(method: str, payload: dict):
                calls.append((method, payload["text"]))
                return {"message_id": len(calls)}

            bot._call = fake_call
            text = (
                "📥 <b>TIN NHẮN VÀO LỆNH • V3.0.0</b>\n"
                "<b>🟢 𝗠𝗨𝗔 𝗧Ă𝗡𝗚: 1.00 USDT</b>\n"
                "🟢 <b>ĐỘ TIN CẬY: CAO – 75.0%</b>"
            )
            message_id = await bot.send(text, enabled=True)
            self.assertEqual(message_id, 1)

        asyncio.run(scenario())
        self.assertEqual(len(calls), 2)
        self.assertIn("TIN NHẮN VÀO LỆNH", calls[0][1])
        self.assertEqual(calls[1][1], "🚨 <b>MUA TĂNG NGAY</b>")

    def test_normal_signal_without_high_confidence_is_still_sent_once(self):
        calls = []

        async def scenario():
            bot = TelegramBotV3("token", "1", lambda *args: None)

            async def fake_call(method: str, payload: dict):
                calls.append((method, payload["text"]))
                return {"message_id": len(calls)}

            bot._call = fake_call
            text = (
                "📥 <b>TIN NHẮN VÀO LỆNH • V3.0.0</b>\n"
                "<b>🔴 𝗠𝗨𝗔 𝗚𝗜Ả𝗠: 1.00 USDT</b>\n"
                "🔴 <b>ĐỘ TIN CẬY: THẤP – 54.0%</b>"
            )
            message_id = await bot.send(text, enabled=True)
            self.assertEqual(message_id, 1)

        asyncio.run(scenario())
        self.assertEqual(len(calls), 1)
        self.assertIn("TIN NHẮN VÀO LỆNH", calls[0][1])


if __name__ == "__main__":
    unittest.main()
