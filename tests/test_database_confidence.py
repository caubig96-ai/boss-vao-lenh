import asyncio
import tempfile
import unittest
from pathlib import Path

from database import Database
from models import Prediction


class DatabaseConfidenceTests(unittest.TestCase):
    def test_confidence_stats_group_low_medium_high(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                db = Database(str(Path(directory) / "test.db"))
                await db.open()
                try:
                    rows = [
                        (1, 0.55, "WIN"),
                        (2, 0.56, "LOSS"),
                        (3, 0.60, "WIN"),
                        (4, 0.63, "WIN"),
                        (5, 0.70, "WIN"),
                        (6, 0.72, "LOSS"),
                        (7, 0.80, "WIN"),
                    ]
                    for open_time, confidence, result in rows:
                        prediction = Prediction(
                            open_time,
                            open_time + 300_000,
                            100.0,
                            100.0,
                            "UP",
                            confidence,
                            0.5,
                            0.5,
                            20,
                            1.0,
                            1,
                            False,
                        )
                        await db.create_signal(prediction)
                        await db.settle(open_time, result, 101.0, 0.0)
                    stats = await db.confidence_stats(0, actual_only=False)
                    return stats
                finally:
                    await db.close()

        stats = asyncio.run(scenario())
        self.assertEqual(stats["LOW"]["wins"], 1)
        self.assertEqual(stats["LOW"]["losses"], 1)
        self.assertAlmostEqual(stats["LOW"]["win_rate"], 50.0)
        self.assertEqual(stats["MEDIUM"]["wins"], 2)
        self.assertEqual(stats["MEDIUM"]["losses"], 0)
        self.assertAlmostEqual(stats["MEDIUM"]["win_rate"], 100.0)
        self.assertEqual(stats["HIGH"]["wins"], 2)
        self.assertEqual(stats["HIGH"]["losses"], 1)
        self.assertAlmostEqual(stats["HIGH"]["win_rate"], 2 / 3 * 100)


if __name__ == "__main__":
    unittest.main()
