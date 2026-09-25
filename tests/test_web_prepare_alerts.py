from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebPrepareAlertsTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "web-iphone" / "index.html").read_text(encoding="utf-8")

    def test_exact_16_patterns_remain_in_web(self):
        self.assertIn("4 nhóm × 4 mẫu", self.source)
        self.assertIn('["RGGRR","G"]', self.source)
        self.assertIn('["RGGRG","R"]', self.source)
        self.assertIn('["RGRRR","G"]', self.source)
        self.assertIn('["RGRRG","R"]', self.source)
        self.assertIn('["GGRGG","G"]', self.source)

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

    def test_last_100_same_pattern_drives_adaptive_mode(self):
        self.assertIn("function decisionFromLast100", self.source)
        self.assertIn('status:item.win===true?"WIN":"LOSS"', self.source)
        self.assertIn('return {status:"NEW"', self.source)
        self.assertIn("A gần nhất THẮNG → giữ màu gốc", self.source)
        self.assertIn("A gần nhất THUA → đảo màu", self.source)

    def test_adaptive_mode_uses_60_percent_threshold(self):
        self.assertIn("function adaptiveDecisionFromRows", self.source)
        self.assertIn("rates.winRate>=60", self.source)
        self.assertIn("rates.lossRate>=60", self.source)
        self.assertIn("GLOBAL_WIN", self.source)
        self.assertIn("GLOBAL_LOSS", self.source)
        self.assertIn("oppositeColor", self.source)


    def test_auto_start_and_history_bootstrap(self):
        self.assertIn("async function autoStart", self.source)
        self.assertIn("async function ensureHistory100", self.source)
        self.assertIn("fetchResolvedCategoryPage", self.source)
        self.assertIn("fetchOlderRoundsFallback", self.source)
        self.assertIn("setTimeout(autoStart,100)", self.source)
        self.assertIn("slice(-6000)", self.source)
        self.assertIn("/100 lệnh", self.source)

    def test_browser_vibration_is_best_effort(self):
        self.assertIn("navigator.vibrate", self.source)

    def test_ios_requires_manual_audio_activation(self):
        self.assertIn("CHẠM ĐỂ KÍCH HOẠT", self.source)
        self.assertIn("AudioContext", self.source)


if __name__ == "__main__":
    unittest.main()
