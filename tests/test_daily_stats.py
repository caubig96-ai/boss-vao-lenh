import os
import tempfile
import unittest

import asyncio

from database import Database
from models import Prediction


class DatabaseTests(unittest.TestCase):
    def test_actual_and_virtual_are_separate(self):
        asyncio.run(self._scenario())

    async def _scenario(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(os.path.join(directory, "test.db"))
            await db.open()
            for index, actual in enumerate((True, False)):
                prediction = Prediction(1000 + index, 2000 + index, 100, 101, "UP",
                                        .6, .6, .6, 100, 1, 1, actual)
                await db.create_signal(prediction)
                await db.settle(1000 + index, "WIN", 102, .8 if actual else 0)
            actual_stats = await db.stats(0, actual_only=True)
            virtual_stats = await db.stats(0, actual_only=False)
            self.assertEqual(actual_stats["wins"], 1)
            self.assertEqual(virtual_stats["wins"], 2)
            self.assertAlmostEqual(actual_stats["pnl"], .8)
            await db.close()


if __name__ == "__main__":
    unittest.main()
