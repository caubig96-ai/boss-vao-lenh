import asyncio
import unittest
from datetime import timezone
from types import SimpleNamespace

from runtime_v353 import CompactTelegramBotV353, TradingSignalBotV3


class V353MessageTests(unittest.TestCase):
    def test_legacy_auto_followup_is_disabled(self):
        self.assertIsNone(
            CompactTelegramBotV353.instant_followup_text(
                "📥 <b>TÍN HIỆU M5</b>\n🟢 <b>MUA TĂNG</b>"
            )
        )

    def test_recommended_action_line_is_exact(self):
        async def scenario():
            bot = object.__new__(TradingSignalBotV3)

            async def fake_calibration(p):
                return {"decided": 40, "win_rate": 72.5}, True

            bot._signal_calibration = fake_calibration
            p = SimpleNamespace(direction="UP", bet_step=2, signal_price=114000.0)
            text = await bot._action_message(p)
            self.assertEqual(text, "🚨 <b>MUA TĂNG NGAY • LỆNH 2 • GIÁ 114,000.00</b>")

        asyncio.run(scenario())

    def test_not_recommended_action_line_is_exact(self):
        async def scenario():
            bot = object.__new__(TradingSignalBotV3)

            async def fake_calibration(p):
                return {"decided": 12, "win_rate": 58.3}, False

            bot._signal_calibration = fake_calibration
            p = SimpleNamespace(direction="DOWN", bet_step=1, signal_price=113950.5)
            text = await bot._action_message(p)
            self.assertEqual(
                text,
                "⚠️ <b>KHÔNG NÊN VÀO LỆNH GIẢM • LỆNH 1 • GIÁ 113,950.50</b>",
            )

        asyncio.run(scenario())

    def test_primary_card_does_not_repeat_advice(self):
        async def scenario():
            bot = object.__new__(TradingSignalBotV3)
            bot.config = SimpleNamespace(timezone=timezone.utc)

            async def fake_calibration(p):
                return {"decided": 40, "win_rate": 72.5}, True

            async def fake_pairs():
                return {"win_pairs": 3, "loss_pairs": 1}

            bot._signal_calibration = fake_calibration
            bot.pair_stats_since_reset = fake_pairs
            p = SimpleNamespace(
                direction="UP",
                market_open_time=0,
                market_close_time=299999,
                confidence=0.66,
                signal_price=114000.0,
                bet_step=1,
                bet_amount=1.0,
            )
            text = await bot.signal_text(p)
            self.assertIn("TÍN HIỆU M5", text)
            self.assertIn("MUA TĂNG", text)
            self.assertIn("72.5%", text)
            self.assertNotIn("NÊN VÀO LỆNH", text)
            self.assertNotIn("MUA TĂNG NGAY", text)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
