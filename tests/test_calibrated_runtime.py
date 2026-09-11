import asyncio
import tempfile
import unittest
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from database import Database
from models import Candle
from runtime_v33 import (
    CALIBRATION_MIN_SAMPLES,
    CALIBRATION_MIN_WIN_RATE,
    CALIBRATION_START_MS,
    CalibratedTelegramBotV3,
    TradingSignalBotV3,
    calibration_quality,
    calibration_stats,
    score_band,
)


class CalibrationPureTests(unittest.TestCase):
    def test_score_bands_are_narrow_and_stable(self):
        self.assertEqual(score_band(0.50)[0], "50.0–54.9")
        self.assertEqual(score_band(0.5499)[0], "50.0–54.9")
        self.assertEqual(score_band(0.55)[0], "55.0–59.9")
        self.assertEqual(score_band(0.6499)[0], "60.0–64.9")
        self.assertEqual(score_band(0.65)[0], "65.0–69.9")
        self.assertEqual(score_band(0.75)[0], "75.0+")

    def test_quality_requires_sample_floor_and_70_percent_default(self):
        icon, quality, qualified = calibration_quality({"decided": CALIBRATION_MIN_SAMPLES - 1, "win_rate": 100.0})
        self.assertEqual(quality, "CHƯA ĐỦ MẪU")
        self.assertFalse(qualified)

        icon, quality, qualified = calibration_quality({"decided": CALIBRATION_MIN_SAMPLES, "win_rate": CALIBRATION_MIN_WIN_RATE})
        self.assertEqual(quality, "CAO")
        self.assertTrue(qualified)

        icon, quality, qualified = calibration_quality({"decided": CALIBRATION_MIN_SAMPLES, "win_rate": CALIBRATION_MIN_WIN_RATE - 0.1})
        self.assertFalse(qualified)

    def test_raw_model_high_score_alone_no_longer_triggers_buy_now(self):
        raw_only = (
            "📥 <b>TIN NHẮN VÀO LỆNH • V3.3.0</b>\n"
            "<b>🟢 𝗠𝗨𝗔 𝗧Ă𝗡𝗚: 1.00 USDT</b>\n"
            "📐 <b>ĐIỂM MÔ HÌNH: 78.0/100</b>"
        )
        self.assertIsNone(CalibratedTelegramBotV3.instant_followup_text(raw_only))

        calibrated = raw_only + "\n🟢 <b>HIỆU CHỈNH: CAO</b>"
        self.assertEqual(
            CalibratedTelegramBotV3.instant_followup_text(calibrated),
            "🚨 <b>MUA TĂNG NGAY</b>",
        )


class CalibrationDatabaseTests(unittest.TestCase):
    def test_calibration_uses_only_post_target_fix_rows(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                db = Database(str(Path(directory) / "bot.db"))
                await db.open()
                try:
                    rows = [
                        # Old row must be ignored even though it is in the same score band.
                        (CALIBRATION_START_MS - 300_000, "WIN"),
                        (CALIBRATION_START_MS + 300_000, "WIN"),
                        (CALIBRATION_START_MS + 600_000, "WIN"),
                        (CALIBRATION_START_MS + 900_000, "LOSS"),
                    ]
                    for open_time, result in rows:
                        await db.conn.execute(
                            """INSERT INTO mode_signals(
                               market_open_time,mode,market_close_time,target_price,direction,confidence,
                               status,result,close_price,created_at,settled_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (open_time, "AUTO", open_time + 299_999, 100.0, "UP", 0.52,
                             "SETTLED", result, 101.0 if result == "WIN" else 99.0, "x", "x"),
                        )
                    await db.conn.commit()
                    stats = await calibration_stats(db, "AUTO", 0.52)
                    self.assertEqual(stats["wins"], 2)
                    self.assertEqual(stats["losses"], 1)
                    self.assertEqual(stats["decided"], 3)
                    self.assertAlmostEqual(stats["win_rate"], 66.6666666, places=4)
                finally:
                    await db.close()

        asyncio.run(scenario())


class DecisionGateTests(unittest.TestCase):
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
                    (open_time, "AUTO", open_time + 299_999, 100.0, "UP", confidence,
                     "SETTLED", result, 101.0 if result == "WIN" else 99.0, "x", "x"),
                )
                index += 1
        await db.conn.commit()
        return CALIBRATION_START_MS + (index + 2) * 300_000

    @staticmethod
    async def _run_decision(wins: int, losses: int):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / "bot.db"))
            await db.open()
            try:
                open_time = await DecisionGateTests._seed_history(db, wins, losses)
                for key, value in (
                    ("analysis_mode", "AUTO"),
                    ("manual_enabled", "1"),
                    ("risk_pause_until", "0"),
                    ("risk_cycle_losses", "0"),
                    ("base_bet", "1"),
                    ("bet_step", "1"),
                    ("payout_rate", "0.8"),
                ):
                    await db.set(key, value)

                bot = object.__new__(TradingSignalBotV3)
                bot.db = db
                bot.config = SimpleNamespace(base_bet=1.0, max_bet=100.0, payout_rate=0.8, timezone=timezone.utc)
                bot.live_m5 = Candle("5m", open_time, open_time + 299_999, 100.0, 101.0, 99.0, 100.1, 1.0, False)
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
                    return "📥 TIN NHẮN VÀO LỆNH\n🟢 HIỆU CHỈNH: CAO\nMUA TĂNG"

                bot.signal_text = fake_signal_text

                prediction = {"AUTO": ("UP", 0.52, 0.55, 0.55, 50)}
                with patch("runtime_v33.all_mode_predictions", return_value=prediction):
                    await bot.make_decision(open_time, 0.0)

                row = await (await db.conn.execute(
                    "SELECT actual FROM signals WHERE market_open_time=?", (open_time,)
                )).fetchone()
                return int(row["actual"]), len(bot.telegram.calls), bot.last_decision_state
            finally:
                await db.close()

    def test_70_percent_with_enough_samples_is_promoted_to_real_signal(self):
        actual, sends, state = asyncio.run(self._run_decision(21, 9))
        self.assertEqual(actual, 1)
        self.assertEqual(sends, 1)
        self.assertEqual(state, "ĐÃ GỬI TELEGRAM")

    def test_60_percent_history_stays_shadow_only(self):
        actual, sends, state = asyncio.run(self._run_decision(18, 12))
        self.assertEqual(actual, 0)
        self.assertEqual(sends, 0)
        self.assertIn("BỎ QUA", state)


if __name__ == "__main__":
    unittest.main()
