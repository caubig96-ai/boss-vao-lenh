import asyncio
import os
import tempfile
import unittest

from database import Database
from runtime_v355 import APP_VERSION, TradingSignalBotV3


class ExactTwoMessagesV355Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "3.5.5")

    def test_action_claim_is_atomic_for_same_m5_open_time(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as temp_dir:
                db = Database(os.path.join(temp_dir, "bot.db"))
                await db.open()
                try:
                    bot = object.__new__(TradingSignalBotV3)
                    bot.db = db
                    open_time = 1_789_000_000_000

                    first, second = await asyncio.gather(
                        bot._claim_action_message(open_time),
                        bot._claim_action_message(open_time),
                    )
                    self.assertEqual(sorted([first, second]), [False, True])

                    await bot._mark_action_sent(open_time)
                    self.assertFalse(await bot._claim_action_message(open_time))
                    self.assertEqual(
                        await db.get(f"action_message_sent:{open_time}", "0"),
                        "1",
                    )
                finally:
                    await db.close()

        asyncio.run(scenario())

    def test_failed_send_claim_can_be_released_for_retry(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as temp_dir:
                db = Database(os.path.join(temp_dir, "bot.db"))
                await db.open()
                try:
                    bot = object.__new__(TradingSignalBotV3)
                    bot.db = db
                    open_time = 1_789_000_300_000
                    self.assertTrue(await bot._claim_action_message(open_time))
                    await bot._release_action_claim(open_time)
                    self.assertTrue(await bot._claim_action_message(open_time))
                finally:
                    await db.close()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
