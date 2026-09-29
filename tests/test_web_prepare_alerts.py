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

    def test_strategy_is_continuous_even_odd_minute_v4(self):
        self.assertIn("const SIGNAL_STEP=600", self.worker)
        self.assertIn("const ENTRY_GRACE_SECONDS=70", self.worker)
        self.assertIn("const PAUSE_SECONDS=1800", self.worker)
        self.assertIn('STRATEGY_VERSION="continuous-even-odd-minute-v4"', self.worker)
        self.assertIn("const SIGNAL_STEP=600", self.source)
        self.assertIn("const PREVIEW_ALERT_LEAD=60", self.source)
        self.assertIn('STRATEGY_VERSION="continuous-even-odd-minute-v4"', self.source)

    def test_even_odd_is_based_on_minute_not_hour(self):
        self.assertIn('minute%10===0?"EVEN":"ODD"', self.worker)
        self.assertIn('return lane==="EVEN"?"MỐC CHẴN":"MỐC LẺ"', self.worker)
        self.assertIn('minute%10===0?"EVEN":"ODD"', self.source)
        self.assertIn('return lane==="EVEN"?"MỐC CHẴN":"MỐC LẺ"', self.source)
        self.assertNotIn('hour%2===0?"EVEN":"ODD"', self.worker + self.source)
        self.assertIn('evenMinuteMarks:["00","10","20","30","40","50"]', self.worker)
        self.assertIn('oddMinuteMarks:["05","15","25","35","45","55"]', self.worker)

    def test_three_color_rules_match_requested_patterns(self):
        self.assertIn("function directionFromThree", self.worker)
        self.assertIn('if(a===b&&b===d)return {direction:a,patternType:"SAME"}', self.worker)
        self.assertIn('if(a===d&&a!==b)return {direction:b,patternType:"ALTERNATE"}', self.worker)
        self.assertIn("fourPreviousMarksForTarget", self.worker)
        self.assertIn("decisionColors=colors.slice(1)", self.worker)

    def test_target_uses_three_previous_marks_from_same_lane(self):
        self.assertIn("t-3*SIGNAL_STEP", self.worker)
        self.assertIn("t-2*SIGNAL_STEP", self.worker)
        self.assertIn("t-SIGNAL_STEP", self.worker)
        self.assertIn("return Number(markTs)-INTERVAL", self.worker)
        self.assertIn("đang chạy 16:00 thì xét dãy LẺ để chuẩn bị 16:05", self.source)
        self.assertIn("đang chạy 16:05 thì xét dãy CHẴN để chuẩn bị 16:10", self.source)

    def test_cloud_enters_every_five_minutes_after_previous_settlement(self):
        self.assertIn("function entryTargetForNow", self.worker)
        self.assertIn("Math.floor(Number(nowSec)/INTERVAL)*INTERVAL", self.worker)
        self.assertIn("elapsed>=0&&elapsed<=ENTRY_GRACE_SECONDS", self.worker)
        self.assertIn("if((state.pendingOrders||[]).length)return", self.worker)
        self.assertIn("await maybeSendSettlement(env,payload,nowSec)", self.worker)
        self.assertIn("await schedulePatternAlert(env,payload)", self.worker)

    def test_web_previews_next_five_minute_target(self):
        self.assertIn("Math.floor(Number(nowSec)/INTERVAL)*INTERVAL+INTERVAL", self.source)
        self.assertIn("PREVIEW_ALERT_LEAD=60", self.source)
        self.assertIn("remain<=PREVIEW_ALERT_LEAD&&remain>0", self.source)
        self.assertIn("Dãy của lệnh kế tiếp", self.source)

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
        self.assertIn('"Lệnh gần nhất MỐC CHẴN: <b>"+laneResultText(previousEven)', self.worker)
        self.assertIn('MỐC LẺ: <b>"+laneResultText(previousOdd)', self.worker)
        self.assertIn('"Phiên mua liên tục: <b>"+frameText(pending.targetStart)', self.worker)

    def test_pattern_signal_endpoint_previews_next_target(self):
        self.assertIn('u.pathname==="/pattern-signal"', self.worker)
        self.assertIn('CLOUD+"/pattern-signal?target="+targetStart', self.source)
        self.assertIn("Math.floor(nowSec/INTERVAL)*INTERVAL+INTERVAL", self.worker)
        self.assertNotIn('u.pathname==="/auto-strategy"', self.worker)
        self.assertNotIn("/auto-strategy?target=", self.source)

    def test_calendar_has_all_twelve_five_minute_slots(self):
        self.assertIn("00/10/20/30/40/50", self.source)
        self.assertIn("05/15/25/35/45/55", self.source)
        self.assertIn("for(const minute of [0,5,10,15,20,25,30,35,40,45,50,55])", self.source)
        self.assertIn("slice(row*12,row*12+12)", self.source)

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
