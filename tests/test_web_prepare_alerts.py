from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WebTimeStrategyTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "web-iphone" / "index.html").read_text(encoding="utf-8")
        self.worker = (ROOT / "cloudflare-worker" / "src" / "index.js").read_text(encoding="utf-8")

    def test_old_color_engines_are_removed(self):
        for token in [
            "BINANCE_KLINES_URL",
            "cachedBinanceAutoStrategy",
            "autoStrategyMode",
            "reverseColorMode",
            "reverseAfterSecondLossActive",
            "lossCapitalMode",
            "toggleAutoStrategyMode",
            "toggleLossCapitalMode",
            "tradeDirectionFromSource",
            "reverse_after_order2_loss",
        ]:
            self.assertNotIn(token, self.worker + self.source)

    def test_even_odd_hour_strategy_constants(self):
        self.assertIn("const SIGNAL_STEP=600", self.worker)
        self.assertIn("const ALERT_LEAD=420", self.worker)
        self.assertIn("const PAUSE_SECONDS=1800", self.worker)
        self.assertIn('STRATEGY_VERSION="even-odd-hour-3color-v2"', self.worker)
        self.assertIn("const SIGNAL_STEP=600", self.source)
        self.assertIn("const ALERT_LEAD=420", self.source)
        self.assertIn('STRATEGY_VERSION="even-odd-hour-3color-v2"', self.source)

    def test_even_odd_is_based_on_local_hour(self):
        self.assertIn('timeZone:"Asia/Ho_Chi_Minh"', self.worker)
        self.assertIn('hour%2===0?"EVEN":"ODD"', self.worker)
        self.assertIn('return lane==="EVEN"?"GIỜ CHẴN":"GIỜ LẺ"', self.worker)
        self.assertIn('minute===30||minute===40||minute===50', self.worker)
        self.assertIn('hour%2===0?"EVEN":"ODD"', self.source)

    def test_three_color_rules_match_requested_patterns(self):
        self.assertIn("function directionFromThree", self.worker)
        self.assertIn('if(a===b&&b===d)return {direction:a,patternType:"SAME"}', self.worker)
        self.assertIn('if(a===d&&a!==b)return {direction:b,patternType:"ALTERNATE"}', self.worker)
        self.assertIn("fourPreviousMarksForTarget", self.worker)
        self.assertIn("decisionColors=colors.slice(1)", self.worker)

    def test_example_1600_1610_1620_targets_1630(self):
        self.assertIn("t-3*SIGNAL_STEP", self.worker)
        self.assertIn("t-2*SIGNAL_STEP", self.worker)
        self.assertIn("t-SIGNAL_STEP", self.worker)
        self.assertIn("return Number(markTs)-INTERVAL", self.worker)
        self.assertIn("16:00–16:10–16:20 → dự đoán 16:30", self.source)

    def test_alert_is_seven_minutes_before_target(self):
        self.assertIn("ALERT_LEAD=420", self.worker)
        self.assertIn("remain<=450&&remain>=390", self.worker)
        self.assertIn("Báo trước 7 phút", self.source)
        self.assertIn("remain<=450&&remain>=390", self.source)

    def test_previous_order_must_settle_before_assigning_next_money_step(self):
        self.assertIn("if((state.pendingOrders||[]).length)return", self.worker)
        self.assertIn("settleDueOrders", self.worker)
        self.assertIn("pendingOrders", self.source)

    def test_win_double_rule_is_preserved(self):
        self.assertIn("function nextStepAfter(step,win)", self.worker)
        self.assertIn("Number(step)===1&&win?2:1", self.worker)
        self.assertIn('label:"Lệnh 2 x2"', self.worker)
        self.assertIn('label:"Lệnh 1"', self.worker)
        self.assertIn("state.step=nextStep", self.worker)
        self.assertIn("Lệnh 2 x2", self.source)
        self.assertIn("const step=Number(cloudTradeState.step||1)===2?2:1", self.source)

    def test_both_even_and_odd_losses_pause_30_minutes(self):
        self.assertIn('state.laneResults.EVEN==="LOSS"&&state.laneResults.ODD==="LOSS"', self.worker)
        self.assertIn("PAUSE_SECONDS=1800", self.worker)
        self.assertIn("state.step=1", self.worker)
        self.assertIn("DỪNG 30 PHÚT", self.worker)
        self.assertIn("DỪNG 30 PHÚT", self.source)

    def test_telegram_shows_four_colors_lane_and_previous_results(self):
        self.assertIn('"4 màu trước: "+fourLine', self.worker)
        self.assertIn('"3 màu quyết định: <b>"+threeLine', self.worker)
        self.assertIn('"🚨 <b>BÁO LỆNH KHUNG "+pending.laneText', self.worker)
        self.assertIn('"Lệnh gần nhất CHẴN: <b>"+laneResultText(previousEven)', self.worker)
        self.assertIn('LẺ: <b>"+laneResultText(previousOdd)', self.worker)

    def test_pattern_signal_endpoint_replaces_auto_strategy_endpoint(self):
        self.assertIn('u.pathname==="/pattern-signal"', self.worker)
        self.assertIn('CLOUD+"/pattern-signal?target="+targetStart', self.source)
        self.assertNotIn('u.pathname==="/auto-strategy"', self.worker)
        self.assertNotIn("/auto-strategy?target=", self.source)

    def test_calendar_keeps_ten_minute_marks(self):
        self.assertIn("00/10/20/30/40/50", self.source)
        self.assertIn("for(const minute of [0,10,20,30,40,50])", self.source)
        self.assertIn("slice(row*6,row*6+6)", self.source)
        self.assertIn("isPatternTarget(slot.t)", self.source)

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
