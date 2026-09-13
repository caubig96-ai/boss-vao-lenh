import asyncio
import tempfile
import unittest
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from database import Database
from models import Candle
from runtime_v33 import CALIBRATION_START_MS
from runtime_v351 import TradingSignalBotV3


class AlwaysSendV351Tests(unittest.TestCase):
    @staticmethod
    async def _seed_history(db: Database, wins: int, losses: int, confidence: float = 0.52) -> int:
        index = 0
        for result, count in (("WIN", wins), ("LOSS", losses)):
            for _ in range(count):
                open_time = CALIBRATION_START_MS + (index + 1) * 300_000
                await db.conn.execute(
                    """INSERT INTO mode_signals(
                       market_open_time,mode,market_close_time,target_price,direction,confidence,
                       status,result,close_price,created_at,settled_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        open_time,
                        "AUTO",
                        open_time + 299_999,
                        100.0,
                        "UP",
                        confidence,
                        "SETTLED",
                        result,
                        101.0 if result == "WIN" else 99.0,
                        "x",
                        "x",
                    ),
                )
                index += 1
        await db.conn.commit()
        return CALIBRATION_START_MS + (index + 2) * 300_000

    @staticmethod
    async def _run_decision(wins: int, losses: int, manual_enabled: bool = True):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / "bot.db"))
            await db.open()
            try:
                open_time = await AlwaysSendV351Tests._seed_history(db, wins, losses)
                for key, value in (
                    ("analysis_mode", "AUTO"),
                    ("manual_enabled", "1" if manual_enabled else "0"),
                    ("risk_pause_until", "0"),
                    ("risk_cycle_losses", "0"),
                    ("base_bet", "1"),
                    ("bet_step", "1"),
                    ("payout_rate", "0.8"),
                    ("stats_reset_at", "0"),
                ):
                    await db.set(key, value)

                bot = object.__new__(TradingSignalBotV3)
                bot.db = db
                bot.config = SimpleNamespace(
                    base_bet=1.0,
                    max_bet=100.0,
                    payout_rate=0.8,
                    timezone=timezone.utc,
                )
                bot.live_m5 = Candle(
                    "5m",
                    open_time,
                    open_time + 299_999,
                    100.0,
                    101.0,
                    99.0,
                    100.1,
                    1.0,
                    False,
                )
                bot.live_price = 100.1
                bot.m1 = []
                bot.m5 = []
                bot.server_offset_ms = 0
                bot.decision_tasks = {}
                bot.last_decision_open = 0
                bot.last_decision_state = ""

                class FakeTelegram:
                    def __init__(self):
                        self.calls = []

                    async def send(self, text, **kwargs):
                        self.calls.append(text)
                        return len(self.calls)

                bot.telegram = FakeTelegram()

                async def fake_signal_text(prediction):
                    return "TIN NHẮN VÀO LỆNH"

                bot.signal_text = fake_signal_text
                prediction = {"AUTO": ("UP", 0.52, 0.55, 0.55, 50)}
                with patch("runtime_v33.all_mode_predictions", return_value=prediction):
                    await bot.make_decision(open_time, 0.0)

                row = await (
                    await db.conn.execute(
                        "SELECT actual,telegram_message_id FROM signals WHERE market_open_time=?",
                        (open_time,),
                    )
                ).fetchone()
                return (
                    int(row["actual"]),
                    row["telegram_message_id"],
                    len(bot.telegram.calls),
                    bot.last_decision_state,
                )
            finally:
                await db.close()

    def test_below_70_percent_still_sends_normal_signal(self):
        actual, message_id, sends, state = asyncio.run(self._run_decision(18, 12))
        self.assertEqual(actual, 1)
        self.assertIsNotNone(message_id)
        self.assertEqual(sends, 1)
        self.assertIn("KHÔNG KHUYẾN KHÍCH", state)

    def test_qualified_signal_is_not_sent_twice(self):
        actual, message_id, sends, state = asyncio.run(self._run_decision(21, 9))
        self.assertEqual(actual, 1)
        self.assertIsNotNone(message_id)
        self.assertEqual(sends, 1)
        self.assertIn("KHUYẾN KHÍCH", state)

    def test_manual_stop_is_not_bypassed(self):
        actual, message_id, sends, state = asyncio.run(
            self._run_decision(18, 12, manual_enabled=False)
        )
        self.assertEqual(actual, 0)
        self.assertIsNone(message_id)
        self.assertEqual(sends, 0)
        self.assertIn("ĐANG TẮT", state)


if __name__ == "__main__":
    unittest.main()
