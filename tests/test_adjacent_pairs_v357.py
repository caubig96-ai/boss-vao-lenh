import asyncio
import os
import tempfile
import unittest

from database import Database
from models import Prediction
from runtime_v357 import APP_VERSION, TradingSignalBotV3


class AdjacentPairsV357Tests(unittest.TestCase):
    def _run_results(self, results):
        async def scenario(path: str):
            db = Database(path)
            await db.open()
            try:
                await db.set_default("stats_reset_at", "0")
                for index, result in enumerate(results, start=1):
                    open_time = index * 300_000
                    prediction = Prediction(
                        open_time,
                        open_time + 299_999,
                        100.0,
                        100.0,
                        "UP",
                        0.60,
                        0.50,
                        0.50,
                        10,
                        1.0,
                        1,
                        True,
                    )
                    self.assertTrue(await db.create_signal(prediction))
                    await db.settle(open_time, result, 101.0, 0.0)
                bot = object.__new__(TradingSignalBotV3)
                bot.db = db
                return await bot.pair_stats_since_reset()
            finally:
                await db.close()

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            return asyncio.run(scenario(path))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def test_version(self):
        self.assertEqual(APP_VERSION, "3.5.7")

    def test_user_example_only_first_two_wins_form_pair(self):
        # W W L W L W -> only orders 1+2 are a same-result adjacent pair.
        stats = self._run_results(["WIN", "WIN", "LOSS", "WIN", "LOSS", "WIN"])
        self.assertEqual(stats["win_pairs"], 1)
        self.assertEqual(stats["loss_pairs"], 0)
        self.assertEqual(stats["unpaired"], 4)

    def test_pair_can_start_after_a_mismatch(self):
        # Fixed (1,2)/(3,4) pairing would miss orders 2+3 here. V3.5.7 must find them.
        stats = self._run_results(["WIN", "LOSS", "LOSS", "WIN"])
        self.assertEqual(stats["win_pairs"], 0)
        self.assertEqual(stats["loss_pairs"], 1)
        self.assertEqual(stats["unpaired"], 2)

    def test_four_consecutive_wins_make_two_non_overlapping_pairs(self):
        stats = self._run_results(["WIN", "WIN", "WIN", "WIN"])
        self.assertEqual(stats["win_pairs"], 2)
        self.assertEqual(stats["loss_pairs"], 0)
        self.assertEqual(stats["unpaired"], 0)


if __name__ == "__main__":
    unittest.main()
