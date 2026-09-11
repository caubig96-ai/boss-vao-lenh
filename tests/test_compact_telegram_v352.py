import asyncio
import unittest
from datetime import timezone
from types import SimpleNamespace

from runtime_v352 import APP_VERSION, CompactTelegramBotV352, TradingSignalBotV3


class CompactTelegramPureTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "3.5.2")

    def test_buy_now_only_for_recommended_card(self):
        self.assertEqual(
            CompactTelegramBotV352.instant_followup_text(
                "🟢 <b>MUA TĂNG</b>\n✅ <b>NÊN VÀO LỆNH</b>"
            ),
            "🚨 <b>MUA TĂNG NGAY</b>",
        )
        self.assertIsNone(
            CompactTelegramBotV352.instant_followup_text(
                "🔴 <b>MUA GIẢM</b>\n⚠️ <b>KHÔNG NÊN VÀO LỆNH</b>"
            )
        )

    def test_detail_button_is_attached_to_compact_entry(self):
        async def scenario():
            bot = CompactTelegramBotV352("token", "1", None)
            bot.detail_open_time = 123456789
            calls = []

            async def fake_call(method, payload):
                calls.append((method, payload))
                return {"message_id": 77}

            bot._call = fake_call
            message_id = await bot.send("📥 <b>TÍN HIỆU M5</b>\n🟢 <b>MUA TĂNG</b>")
            self.assertEqual(message_id, 77)
            markup = calls[0][1]["reply_markup"]
            self.assertEqual(markup["inline_keyboard"][0][0]["callback_data"], "detail_123456789")
            self.assertEqual(markup["inline_keyboard"][0][0]["text"], "📋 CHI TIẾT")

        asyncio.run(scenario())


class CompactRuntimeTests(unittest.TestCase):
    def test_signal_card_contains_only_requested_summary_fields(self):
        async def scenario():
            bot = object.__new__(TradingSignalBotV3)
            bot.config = SimpleNamespace(timezone=timezone.utc)

            async def fake_calibration(p):
                return {"decided": 40, "win_rate": 72.5}, True

            async def fake_pairs():
                return {"win_pairs": 4, "loss_pairs": 2, "other_pairs": 1, "complete_pairs": 7, "unpaired": 0}

            bot._signal_calibration = fake_calibration
            bot.pair_stats_since_reset = fake_pairs
            p = SimpleNamespace(
                direction="UP",
                market_open_time=0,
                market_close_time=299999,
                confidence=0.66,
                signal_price=114000.0,
                bet_step=2,
                bet_amount=2.0,
            )
            text = await bot.signal_text(p)
            self.assertIn("MUA TĂNG", text)
            self.assertIn("NÊN VÀO LỆNH", text)
            self.assertIn("00:00–00:04", text)
            self.assertIn("72.5%", text)
            self.assertIn("4 thắng", text)
            self.assertIn("2 thua", text)
            self.assertIn("LỆNH 2", text)
            self.assertIn("114,000.00", text)
            self.assertNotIn("M1 score", text)
            self.assertNotIn("Mẫu lịch sử", text)

        asyncio.run(scenario())

    def test_result_is_one_short_line_with_direction_and_bet_step(self):
        async def scenario():
            bot = object.__new__(TradingSignalBotV3)
            row = {"direction": "DOWN", "bet_step": 2}
            loss = await bot.result_text(row, 100.0, "LOSS", -1.0, 101.0)
            win = await bot.result_text(row, 100.0, "WIN", 0.8, 101.0)
            self.assertEqual(loss, "❌ <b>THUA GIẢM • LỆNH 2</b>")
            self.assertEqual(win, "✅ <b>THẮNG GIẢM • LỆNH 2</b>")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
