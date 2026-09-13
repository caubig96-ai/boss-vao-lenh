import asyncio
import unittest

from config import Config
from main import M1_24H, M5_24H, TradingSignalBot


class LiveMarketTests(unittest.TestCase):
    def make_bot(self) -> TradingSignalBot:
        return TradingSignalBot(Config(telegram_token="test", telegram_chat_id="1"))

    def test_aggtrade_moves_live_candle_on_every_tick(self):
        async def scenario():
            bot = self.make_bot()
            await bot.handle_market_message({"e": "aggTrade", "E": 10_000, "T": 10_000, "p": "100"})
            await bot.handle_market_message({"e": "aggTrade", "E": 10_100, "T": 10_100, "p": "105"})
            await bot.handle_market_message({"e": "aggTrade", "E": 10_200, "T": 10_200, "p": "98"})

            self.assertEqual(bot.trade_ticks, 3)
            self.assertEqual(bot.live_price, 98.0)
            self.assertEqual(bot.live_m1.open, 100.0)
            self.assertEqual(bot.live_m1.high, 105.0)
            self.assertEqual(bot.live_m1.low, 98.0)
            self.assertEqual(bot.live_m1.close, 98.0)
            self.assertEqual(bot.live_m5.open, 100.0)
            self.assertEqual(bot.live_m5.close, 98.0)

            # Sang phút mới: M1 mở bucket mới từ tick đầu tiên; M5 vẫn tiếp tục cùng bucket.
            await bot.handle_market_message({"e": "aggTrade", "E": 60_001, "T": 60_001, "p": "101"})
            self.assertEqual(bot.live_m1.open_time, 60_000)
            self.assertEqual(bot.live_m1.open, 101.0)
            self.assertEqual(bot.live_m1.high, 101.0)
            self.assertEqual(bot.live_m1.low, 101.0)
            self.assertEqual(bot.live_m1.close, 101.0)
            self.assertEqual(bot.live_m5.open_time, 0)
            self.assertEqual(bot.live_m5.close, 101.0)

        asyncio.run(scenario())

    def test_out_of_order_trade_does_not_roll_chart_back(self):
        async def scenario():
            bot = self.make_bot()
            await bot.handle_market_message({"e": "aggTrade", "E": 60_100, "T": 60_100, "p": "110"})
            await bot.handle_market_message({"e": "aggTrade", "E": 60_200, "T": 59_900, "p": "90"})
            self.assertEqual(bot.live_price, 110.0)
            self.assertEqual(bot.live_m1.open_time, 60_000)
            self.assertEqual(bot.live_m1.close, 110.0)
            self.assertEqual(bot.trade_ticks, 1)

        asyncio.run(scenario())

    def test_fresher_trade_is_not_overwritten_by_older_kline_event(self):
        async def scenario():
            bot = self.make_bot()
            await bot.handle_market_message({"e": "aggTrade", "E": 70_000, "T": 70_000, "p": "105"})
            await bot.handle_market_message({
                "e": "kline",
                "E": 69_000,
                "k": {
                    "i": "1m", "t": 60_000, "T": 119_999,
                    "o": "100", "h": "104", "l": "99", "c": "104", "v": "12", "x": False,
                },
            })
            self.assertEqual(bot.live_m1.open, 100.0)  # open chính thức Binance
            self.assertEqual(bot.live_m1.high, 105.0)
            self.assertEqual(bot.live_m1.low, 99.0)
            self.assertEqual(bot.live_m1.close, 105.0)  # tick mới hơn vẫn thắng
            self.assertEqual(bot.live_price, 105.0)

        asyncio.run(scenario())

    def test_memory_windows_are_exactly_24_hours(self):
        bot = self.make_bot()
        self.assertEqual(bot.m1.maxlen, M1_24H)
        self.assertEqual(bot.m5.maxlen, M5_24H)
        self.assertEqual(M1_24H, 1440)
        self.assertEqual(M5_24H, 288)


if __name__ == "__main__":
    unittest.main()
