import asyncio
import unittest
from datetime import timezone
from types import SimpleNamespace

from runtime_v356 import APP_VERSION, TradingSignalBotV3


class EntrySummaryV356Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "3.5.6")

    def test_entry_card_has_separator_and_total_win_loss(self):
        async def scenario():
            bot = object.__new__(TradingSignalBotV3)
            bot.config = SimpleNamespace(timezone=timezone.utc)

            async def fake_calibration(p):
                return {"decided": 40, "win_rate": 62.5}, False

            async def fake_pairs():
                return {"win_pairs": 2, "loss_pairs": 1}

            async def fake_totals():
                return {"wins": 7, "losses": 3}

            bot._signal_calibration = fake_calibration
            bot.pair_stats_since_reset = fake_pairs
            bot._entry_totals_since_reset = fake_totals

            p = SimpleNamespace(
                direction="DOWN",
                market_open_time=0,
                market_close_time=299999,
                confidence=0.57,
                signal_price=78714.70,
                bet_step=2,
                bet_amount=2.0,
            )

            text = await bot.signal_text(p)
            self.assertIn("🔴 <b>MUA GIẢM</b>\n━━━━━━━━━━━━━━━━━━━━\n⏰", text)
            self.assertIn("📋 Tổng: ✅ 7 thắng • ❌ 3 thua", text)
            self.assertIn("🔗 Cặp: ✅ 2 thắng • ❌ 1 thua", text)
            self.assertIn("Dự kiến thắng: <b>62.5%</b>", text)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
