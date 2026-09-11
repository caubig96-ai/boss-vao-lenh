import asyncio
import unittest

from config import Config
from runtime_v35 import APP_VERSION, TradingSignalBotV3


class BinanceKlineOnlyV35Tests(unittest.TestCase):
    def make_bot(self) -> TradingSignalBotV3:
        return TradingSignalBotV3(Config(telegram_token="test", telegram_chat_id="1"))

    def test_version_and_source_marker(self):
        bot = self.make_bot()
        self.assertEqual(APP_VERSION, "3.5.0")
        self.assertEqual(bot.candle_source, "BINANCE_FUTURES_KLINE_ONLY")

    def test_aggtrade_updates_price_but_never_creates_candles(self):
        async def scenario():
            bot = self.make_bot()
            await bot.handle_market_message({"e": "aggTrade", "E": 10_000, "T": 10_000, "p": "100"})
            await bot.handle_market_message({"e": "aggTrade", "E": 10_100, "T": 10_100, "p": "105"})
            await bot.handle_market_message({"e": "aggTrade", "E": 10_200, "T": 10_200, "p": "98"})

            self.assertEqual(bot.trade_ticks, 3)
            self.assertEqual(bot.live_price, 98.0)
            self.assertIsNone(bot.live_m1)
            self.assertIsNone(bot.live_m5)

        asyncio.run(scenario())

    def test_binance_kline_is_authoritative_ohlc_even_after_newer_trade(self):
        async def scenario():
            bot = self.make_bot()
            kline = {
                "e": "kline",
                "E": 70_000,
                "k": {
                    "i": "1m",
                    "t": 60_000,
                    "T": 119_999,
                    "o": "100",
                    "h": "104",
                    "l": "99",
                    "c": "103",
                    "v": "12",
                    "x": False,
                },
            }
            await bot.handle_market_message(kline)
            self.assertEqual(bot.live_m1.open, 100.0)
            self.assertEqual(bot.live_m1.high, 104.0)
            self.assertEqual(bot.live_m1.low, 99.0)
            self.assertEqual(bot.live_m1.close, 103.0)

            # A later trade may move the displayed PRICE but must not stretch the
            # candle to 110 or overwrite Binance's kline close.
            await bot.handle_market_message({"e": "aggTrade", "E": 70_100, "T": 70_100, "p": "110"})
            self.assertEqual(bot.live_price, 110.0)
            self.assertEqual(bot.live_m1.open, 100.0)
            self.assertEqual(bot.live_m1.high, 104.0)
            self.assertEqual(bot.live_m1.low, 99.0)
            self.assertEqual(bot.live_m1.close, 103.0)

            # The next official Binance kline snapshot replaces OHLC exactly.
            updated = {
                "e": "kline",
                "E": 70_200,
                "k": {
                    "i": "1m",
                    "t": 60_000,
                    "T": 119_999,
                    "o": "100",
                    "h": "106",
                    "l": "98",
                    "c": "105",
                    "v": "15",
                    "x": False,
                },
            }
            await bot.handle_market_message(updated)
            self.assertEqual(bot.live_m1.open, 100.0)
            self.assertEqual(bot.live_m1.high, 106.0)
            self.assertEqual(bot.live_m1.low, 98.0)
            self.assertEqual(bot.live_m1.close, 105.0)

        asyncio.run(scenario())

    def test_m5_decision_is_scheduled_from_kline_not_aggtrade(self):
        async def scenario():
            bot = self.make_bot()
            scheduled = []
            bot.schedule_decision = lambda candle, event_time: scheduled.append((candle.open_time, event_time))

            await bot.handle_market_message({"e": "aggTrade", "E": 300_100, "T": 300_100, "p": "200"})
            self.assertEqual(scheduled, [])
            self.assertIsNone(bot.live_m5)

            await bot.handle_market_message({
                "e": "kline",
                "E": 300_200,
                "k": {
                    "i": "5m",
                    "t": 300_000,
                    "T": 599_999,
                    "o": "201",
                    "h": "203",
                    "l": "199",
                    "c": "202",
                    "v": "20",
                    "x": False,
                },
            })
            self.assertEqual(scheduled, [(300_000, 300_200)])
            self.assertEqual(bot.live_m5.open, 201.0)
            self.assertEqual(bot.live_m5.close, 202.0)

        asyncio.run(scenario())

    def test_out_of_order_trade_does_not_roll_price_back(self):
        async def scenario():
            bot = self.make_bot()
            await bot.handle_market_message({"e": "aggTrade", "E": 80_000, "T": 80_000, "p": "120"})
            await bot.handle_market_message({"e": "aggTrade", "E": 80_100, "T": 79_000, "p": "90"})
            self.assertEqual(bot.live_price, 120.0)
            self.assertEqual(bot.trade_ticks, 1)
            self.assertIsNone(bot.live_m1)
            self.assertIsNone(bot.live_m5)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
