from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebPrepareAlertsTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "web-iphone" / "index.html").read_text(encoding="utf-8")

    def test_exact_12_image_patterns_are_the_only_active_web_rules(self):
        self.assertIn("Boss 12 Mẫu", self.source)
        self.assertIn("3 nhóm × 4 mẫu", self.source)
        expected = [
            '["RGGRR","R"]', '["GGRRR","G"]', '["GRRGG","G"]', '["RRGGG","R"]',
            '["RGRRR","R"]', '["GRGGR","R"]', '["RRGRR","R"]', '["GGRGR","R"]',
            '["RGRRG","G"]', '["GRGGG","G"]', '["RRGRG","G"]', '["GGRGG","G"]',
        ]
        for item in expected:
            self.assertIn(item, self.source)
        self.assertNotIn('["GRRGR","G"]', self.source)
        self.assertNotIn('["RGGRG","R"]', self.source)
        self.assertNotIn('["GGRRG","R"]', self.source)
        self.assertNotIn('["RRGGR","G"]', self.source)
        self.assertNotIn("4 nhóm × 4 mẫu", self.source)
        self.assertNotIn("16 mô hình 5 nến", self.source)

    def test_prepare_alert_happens_twice_for_three_seconds(self):
        self.assertIn("remain<=60&&remain>30", self.source)
        self.assertIn("remain<=30&&remain>0", self.source)
        self.assertIn("CHUẨN BỊ VÀO LỆNH", self.source)
        self.assertIn("CÒN 30 GIÂY", self.source)
        self.assertIn("threeSecondAlert", self.source)
        self.assertIn("prepare_60_start", self.source)
        self.assertIn("prepare_30_start", self.source)

    def test_final_signal_uses_closed_live_round(self):
        self.assertIn("async function finalizeLiveRound", self.source)
        self.assertIn("closed=await fetchRound(liveStart)", self.source)
        self.assertIn("const code=info.prefix+closed.c", self.source)
        self.assertIn("MUA XANH", self.source)
        self.assertIn("MUA ĐỎ", self.source)

    def test_adaptive_mode_uses_three_samples_and_60_percent(self):
        self.assertIn("function adaptiveDecisionFromRows", self.source)
        self.assertIn("const MIN_SAMPLES=3", self.source)
        self.assertIn("const THRESHOLD=60", self.source)
        self.assertIn("winRate>lossRate&&winRate>=THRESHOLD", self.source)
        self.assertIn("lossRate>winRate&&lossRate>=THRESHOLD", self.source)
        self.assertIn('mode:"REVERSE_RATE"', self.source)
        self.assertIn("oppositeColor", self.source)

    def test_pattern_stats_use_rolling_last_100_raw_signals(self):
        self.assertIn("const recent=rawPatternSettled().slice(-100)", self.source)
        self.assertIn('recentCount+"/100 lệnh"', self.source)
        self.assertIn("Cửa sổ trượt 100 lệnh", self.source)
        self.assertIn("12 mẫu màu", self.source)

    def test_24h_calendar_uses_288_five_minute_slots(self):
        self.assertIn("Lịch 24 giờ theo nhóm màu nến", self.source)
        self.assertIn("288 ô", self.source)
        self.assertIn("function buildCalendar24h", self.source)
        self.assertIn("for(let i=0;i<288;i++)", self.source)
        self.assertIn("renderCalendar24h", self.source)
        self.assertIn("INTERVAL*1000", self.source)

    def test_cloud_history_and_daily_tool_orders_are_separate(self):
        self.assertIn("function rawPatternSettled", self.source)
        self.assertIn("function recordToolOrder", self.source)
        self.assertIn("boss_tool_orders", self.source)
        self.assertIn("Lệnh Telegram hôm nay", self.source)
        self.assertIn("todayToolHistory", self.source)

    def test_auto_start_loads_cloud_history(self):
        self.assertIn("async function autoStart", self.source)
        self.assertIn("fetchCloudHistory(false)", self.source)
        self.assertIn("async function ensureHistory100", self.source)
        self.assertIn("setTimeout(autoStart,100)", self.source)
        self.assertIn("slice(-6000)", self.source)

    def test_browser_vibration_is_best_effort(self):
        self.assertIn("navigator.vibrate", self.source)

    def test_ios_requires_manual_audio_activation(self):
        self.assertIn("CHẠM ĐỂ KÍCH HOẠT", self.source)
        self.assertIn("AudioContext", self.source)


if __name__ == "__main__":
    unittest.main()
