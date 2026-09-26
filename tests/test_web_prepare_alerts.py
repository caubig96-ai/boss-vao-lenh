from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WebTimeStrategyTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "web-iphone" / "index.html").read_text(encoding="utf-8")
        self.worker = (ROOT / "cloudflare-worker" / "src" / "index.js").read_text(encoding="utf-8")

    def test_old_pattern_strategy_is_removed(self):
        self.assertNotIn("PATTERN_GROUPS", self.source)
        self.assertNotIn("PATTERNS=", self.source)
        self.assertNotIn("recentTwoDecision", self.source)
        self.assertNotIn("buildAdaptiveHistory", self.source)
        self.assertNotIn("decisionFor", self.worker)
        self.assertNotIn("settledSignals", self.worker)
        self.assertNotIn("PATTERN_VARIANTS", self.worker)

    def test_even_time_strategy_constants(self):
        self.assertIn("const SOURCE_STEP=600", self.source)
        self.assertIn("const ENTRY_DELAY=900", self.source)
        self.assertIn("const SOURCE_STEP=600", self.worker)
        self.assertIn("const ENTRY_DELAY=900", self.worker)
        self.assertIn('STRATEGY_VERSION="even-10m-3c-filter-v2"', self.worker)

    def test_three_candle_filter_controls_entry(self):
        self.assertIn('FILTER_PATTERNS=new Set(["GRG","RGR","GRR","RGG"])', self.source)
        self.assertIn('FILTER_PATTERNS=new Set(["GRG","RGR","GRR","RGG"])', self.worker)
        self.assertIn("function sourcePatternAt", self.source)
        self.assertIn("async function sourcePatternAt", self.worker)
        self.assertIn("if(!sourcePattern||!sourcePattern.allowed)return", self.worker)
        self.assertIn("direction:sourcePattern.direction", self.worker)
        self.assertIn("if(!s.allowed)", self.source)

    def test_one_minute_telegram_alert(self):
        self.assertIn("remain<=60&&remain>30", self.source)
        self.assertIn("CÒN 1 PHÚT • VÀO LỆNH PHIÊN SAU", self.source)
        self.assertIn("CÒN ~1 PHÚT • BÁO LỆNH PHIÊN SAU", self.worker)
        self.assertIn("3 nến:", self.worker)
        self.assertIn("XĐX / ĐXĐ / XĐĐ / ĐXX", self.worker)

    def test_two_losses_skip_two_beats(self):
        self.assertIn("SKIP_BEATS_AFTER_TWO_LOSSES=2", self.source)
        self.assertIn("SKIP_BEATS_AFTER_TWO_LOSSES=2", self.worker)
        self.assertIn("skipRemaining=SKIP_BEATS_AFTER_TWO_LOSSES", self.source)
        self.assertIn("state.skipSignals=SKIP_BEATS_AFTER_TWO_LOSSES", self.worker)
        self.assertIn("BỎ 2 NHỊP KẾ TIẾP", self.worker)

    def test_24h_calendar_is_24_by_12(self):
        self.assertIn("24 hàng giờ", self.source)
        self.assertIn("12 ô × 5 phút", self.source)
        self.assertIn("for(let i=0;i<288;i++)", self.source)
        self.assertIn("for(let row=0;row<24;row++)", self.source)
        self.assertIn("slice(row*12,row*12+12)", self.source)
        self.assertIn('sum.textContent="V "+rowW+" • X "+rowL+" • · "+rowN', self.source)

    def test_result_message_and_reset_remain(self):
        self.assertIn("THẮNG LỆNH", self.worker)
        self.assertIn("THUA LỆNH", self.worker)
        self.assertIn("Lãi/lỗ lệnh này", self.worker)
        self.assertIn('u.pathname==="/trade-reset"', self.worker)
        self.assertIn("resetTradeStateAndHistory", self.source)

    def test_exact_target_settlement_remains(self):
        self.assertIn("apiCategory(Number(pending.targetStart)", self.worker)
        self.assertIn("maybeSendSettlement", self.worker)


if __name__ == "__main__":
    unittest.main()
