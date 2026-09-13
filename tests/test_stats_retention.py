import asyncio
import os
import tempfile
import unittest

from config import Config
from database import Database
from main import TradingSignalBot
from models import Prediction


class StatsRetentionTests(unittest.TestCase):
    def test_telegram_stats_keep_old_days_until_manual_reset(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                db = Database(os.path.join(directory, "stats.db"))
                await db.open()
                await db.set_default("stats_reset_at", "0")
                await db.set_default("current_balance", "10")

                old_signal = Prediction(1_000, 301_000, 100, 100, "UP", .6, .6, .6, 20, 1, 1, True)
                await db.create_signal(old_signal)
                await db.settle(old_signal.market_open_time, "WIN", 101, .8)

                bot = TradingSignalBot(Config(telegram_token="test", telegram_chat_id="1"))
                bot.db = db
                text = await bot.stats_text()
                self.assertIn("THỐNG KÊ TỪ LẦN RESET", text)
                self.assertIn("🟢 Thắng: <b>1</b>", text)
                self.assertIn("📅 Hôm nay: 0 thắng", text)
                await db.close()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
