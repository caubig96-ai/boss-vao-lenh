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
        self.assertIn('STRATEGY_VERSION="even-10m-plus15-v1"', self.worker)

    def test_source_color_is_used_15_minutes_later(self):
        self.assertIn("sourceStartForTarget", self.source)
        self.assertIn("sourceStartForTarget(t)", self.source)
        self.assertIn("direction=byTime.get(sourceT)?.c||null", self.source)
        self.assertIn("sourceStart=sourceStartForTarget(targetStart)", self.worker)
        self.assertIn("direction:sourceColor", self.worker)

    def test_one_minute_telegram_alert(self):
        self.assertIn("remain<=60&&remain>30", self.source)
        self.assertIn("CÒN 1 PHÚT • VÀO LỆNH PHIÊN SAU", self.source)
        self.assertIn("CÒN ~1 PHÚT • BÁO LỆNH PHIÊN SAU", self.worker)
        self.assertIn("Mốc lấy màu:", self.worker)
        self.assertIn("sau 15 phút mua cùng màu", self.worker)

    def test_two_losses_skip_two_beats(self):
        self.assertIn("SKIP_BEATS_AFTER_TWO_LOSSES=2", self.source)
        self.assertIn("SKIP_BEATS_AFTER_TWO_LOSSES=2", self.worker)
        self.assertIn("skipRemaining=SKIP_BEATS_AFTER_TWO_LOSSES", self.source)
        self.assertIn("state.skipSignals=SKIP_BEATS_AFTER_TWO_LOSSES", self.worker)
        self.assertIn("BỎ 2 NHỊP KẾ TIẾP", self.worker)

    def test_24h_calendar_shows_only_six_order_slots_per_hour(self):
        self.assertIn("24 hàng giờ", self.source)
        self.assertIn("05/15/25/35/45/55", self.source)
        self.assertIn("for(const minute of [5,15,25,35,45,55])", self.source)
        self.assertIn("for(let row=0;row<24;row++)", self.source)
        self.assertIn("slice(row*6,row*6+6)", self.source)
        self.assertNotIn('status="SOURCE"', self.source)
        self.assertIn('status="SKIP"', self.source)
        self.assertIn('status="WAIT"', self.source)
        self.assertIn('d.textContent="B"', self.source)
        self.assertNotIn('d.textContent="·"', self.source)
        self.assertIn('sum.textContent="V "+rowW+" • X "+rowL+" • B "+rowB', self.source)

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
