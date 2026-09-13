import asyncio
import tempfile
import unittest
from pathlib import Path

from database import Database
from models import Candle, Prediction


class OfficialM5TargetTests(unittest.TestCase):
    def test_closed_binance_m5_open_replaces_provisional_target_before_scoring(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                db = Database(str(Path(directory) / "bot.db"))
                await db.open()
                try:
                    open_time = 300_000
                    close_time = 599_999

                    # Simulate a provisional target captured from the first aggTrade.
                    # It is intentionally below the official Binance M5 open, which
                    # would otherwise turn a visibly red candle into a false LOSS DOWN.
                    provisional_target = 99.0
                    official_open = 100.0
                    official_close = 99.5

                    prediction = Prediction(
                        open_time,
                        close_time,
                        provisional_target,
                        99.2,
                        "DOWN",
                        0.70,
                        0.40,
                        0.40,
                        20,
                        1.0,
                        1,
                        True,
                    )
                    self.assertTrue(await db.create_signal(prediction))
                    await db.create_mode_signals(
                        open_time,
                        close_time,
                        provisional_target,
                        {"AUTO": ("DOWN", 0.70, 0.40, 0.40, 20)},
                    )

                    # Binance's final M5 kline is authoritative: open=100, close=99.5.
                    # save_candle must rewrite all still-pending targets to open=100
                    # before runtime settles the selected signal and shadow modes.
                    await db.save_candle(
                        Candle(
                            "5m",
                            open_time,
                            close_time,
                            official_open,
                            101.0,
                            99.0,
                            official_close,
                            123.0,
                            True,
                        )
                    )

                    selected = (await db.pending())[0]
                    shadow = (await db.pending_modes())[0]
                    self.assertEqual(float(selected["target_price"]), official_open)
                    self.assertEqual(float(shadow["target_price"]), official_open)

                    await db.settle_mode_signals(open_time, official_close)
                    stats = await db.mode_stats(0)
                    self.assertEqual(stats["AUTO"]["wins"], 1)
                    self.assertEqual(stats["AUTO"]["losses"], 0)
                finally:
                    await db.close()

        asyncio.run(scenario())

    def test_closed_m1_does_not_rewrite_m5_signal_target(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                db = Database(str(Path(directory) / "bot.db"))
                await db.open()
                try:
                    prediction = Prediction(
                        300_000,
                        599_999,
                        99.0,
                        99.2,
                        "DOWN",
                        0.60,
                        0.45,
                        0.45,
                        10,
                        1.0,
                        1,
                        False,
                    )
                    await db.create_signal(prediction)
                    await db.save_candle(
                        Candle("1m", 300_000, 359_999, 123.0, 124.0, 122.0, 122.5, 10.0, True)
                    )
                    selected = (await db.pending())[0]
                    self.assertEqual(float(selected["target_price"]), 99.0)
                finally:
                    await db.close()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
