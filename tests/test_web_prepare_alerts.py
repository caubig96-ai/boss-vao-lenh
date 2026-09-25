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

    def test_last_100_same_pattern_gate(self):
        self.assertIn("function decisionFromLast100", self.source)
        self.assertIn('status:item.win===true?"WIN":"LOSS"', self.source)
        self.assertIn('return {allow:true,status:"NEW"', self.source)
        self.assertIn("BỎ MẪU • GẦN NHẤT THUA", self.source)

    def test_pattern_rate_must_be_at_least_60_percent(self):
        self.assertIn("function currentPatternRateDecision", self.source)
        self.assertIn("allow:rate>=60", self.source)
        self.assertIn("TỶ LỆ < 60%", self.source)
        self.assertIn("yêu cầu từ 60% trở lên", self.source)

    def test_browser_vibration_is_best_effort(self):
        self.assertIn("navigator.vibrate", self.source)

    def test_ios_requires_manual_audio_activation(self):
        self.assertIn("CHẠM ĐỂ KÍCH HOẠT", self.source)
        self.assertIn("AudioContext", self.source)


if __name__ == "__main__":
    unittest.main()
