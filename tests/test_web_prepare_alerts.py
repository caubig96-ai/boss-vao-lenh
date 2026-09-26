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
        self.assertIn("const ENTRY_DELAY=600", self.source)
        self.assertIn("const SOURCE_STEP=600", self.worker)
        self.assertIn("const ENTRY_DELAY=600", self.worker)
        self.assertIn('STRATEGY_VERSION="even-10m-2loss-waitwin-v4"', self.worker)

    def test_source_color_timing_is_preserved_before_auto_strategy_decision(self):
        self.assertIn("sourceStartForTarget", self.source)
        self.assertIn("sourceStartForTarget(t)", self.source)
        self.assertIn("direction=byTime.get(sourceT)?.c||null", self.source)
        self.assertIn("sourceStart=sourceStartForTarget(targetStart)", self.worker)
        self.assertIn("autoStrategyAnalysis(payload,targetStart)", self.worker)
        self.assertIn("const direction=auto.direction||sourceColor", self.worker)

    def test_one_minute_telegram_alert(self):
        self.assertIn("remain<=60&&remain>30", self.source)
        self.assertIn("CÒN 1 PHÚT • VÀO LỆNH PHIÊN SAU", self.source)
        self.assertIn("CÒN ~1 PHÚT • BÁO LỆNH PHIÊN SAU", self.worker)
        self.assertIn("Mốc lấy màu:", self.worker)
        self.assertIn("vào phiên +10 phút, chốt màu ở +15 phút", self.worker)

    def test_signal_is_not_shown_early(self):
        self.assertIn("function isEntryAlertWindow", self.source)
        self.assertIn("alertStartForTarget", self.source)
        self.assertIn('?"CHỜ "+shortClock(alertAt)', self.source)
        self.assertIn("const secondsToTarget=targetStart-nowSec", self.worker)
        self.assertIn("if(secondsToTarget>70||secondsToTarget<=45)return", self.worker)
        self.assertIn("17:00 -> order frame 17:10-17:15 -> alert around 17:09", self.worker)

    def test_previous_order_must_settle_before_next_order(self):
        self.assertIn("lastResultWin:null", self.worker)
        self.assertIn("state.lastResultWin=win", self.worker)
        self.assertIn("if(state.pending&&Number(state.pending.targetStart)!==targetStart)return", self.worker)
        self.assertIn("if(pending&&Number(pending.targetStart)!==targetStart)return", self.source)
        self.assertIn("CHỜ KẾT QUẢ LỆNH TRƯỚC", self.source)
        self.assertIn("Tool vẫn theo dõi đúng giờ và màu nến", self.source)
        self.assertNotIn("state.waitForWin=true", self.worker)
        self.assertNotIn("SKIP_BEATS_AFTER_TWO_LOSSES", self.source)
        self.assertNotIn("SKIP_BEATS_AFTER_TWO_LOSSES", self.worker)

    def test_24h_calendar_shows_only_six_order_slots_per_hour_newest_first(self):
        self.assertIn("24 hàng giờ", self.source)
        self.assertIn("00/10/20/30/40/50", self.source)
        self.assertIn("for(const minute of [0,10,20,30,40,50])", self.source)
        self.assertIn("for(let row=23;row>=0;row--)", self.source)
        self.assertIn("slice(row*6,row*6+6)", self.source)
        self.assertNotIn('status="SOURCE"', self.source)
        self.assertNotIn('status="SKIP"', self.source)
        self.assertIn('status="WAIT"', self.source)
        self.assertNotIn('d.textContent="B"', self.source)
        self.assertNotIn('d.textContent="·"', self.source)
        self.assertIn('sum.textContent="V "+rowW+" • X "+rowL+" • C✓ "+rowCW+" • C× "+rowCL', self.source)

    def test_loss_capital_mode_has_toggle_endpoint_and_1_1_2_4_plan(self):
        self.assertIn("lossCapitalMode:false", self.worker)
        self.assertIn('u.pathname==="/trade-mode"', self.worker)
        self.assertIn("function tradePlan", self.worker)
        self.assertIn("capitalStage===2?1:capitalStage===3?2:4", self.worker)
        self.assertIn("if(state.lossCapitalMode&&state.lossStreak>=4)state.lossStreak=0", self.worker)
        self.assertIn('id="lossCapitalModeBtn"', self.source)
        self.assertIn("toggleLossCapitalMode", self.source)
        self.assertIn("function historicalTradePlan", self.source)
        self.assertIn("if(lossCapitalMode&&lossStreak>=4)lossStreak=0", self.source)

    def test_auto_strategy_replaces_fixed_reverse_rule(self):
        self.assertIn("autoStrategyMode:true", self.worker)
        self.assertIn("function autoStrategyAnalysis", self.worker)
        self.assertIn('"reverse_after_order2_loss"', self.worker)
        self.assertIn('"pattern2","pattern3","pattern4","reverse_after_order2_loss"', self.worker)
        self.assertIn("AUTO_VALIDATE_SECONDS=6*3600", self.worker)
        self.assertIn("AUTO_WINDOW_SECONDS=24*3600", self.worker)
        self.assertIn('u.pathname==="/auto-strategy"', self.worker)
        self.assertIn('id="autoStrategyModeBtn"', self.source)
        self.assertIn("toggleAutoStrategyMode", self.source)
        self.assertNotIn('id="reverseColorModeBtn"', self.source)
        self.assertNotIn("toggleReverseColorMode", self.source)

    def test_24h_calendar_uses_auto_selected_candidate(self):
        self.assertIn("const selectedId=autoMode?(autoStrategySnapshot?.id||\"source\"):\"source\"", self.source)
        self.assertIn("autoPatternMapForCalendar", self.source)
        self.assertIn("autoDirectionForCalendar", self.source)
        self.assertIn('selectedId==="reverse_after_order2_loss"', self.source)
        self.assertIn("autoConsecutiveLosses>=2", self.source)
        self.assertIn("autoStrategySnapshot?.name", self.source)

    def test_loss_capital_mode_preserves_win_double_rule(self):
        self.assertIn("Number(step)===1&&win?2:1", self.worker)
        self.assertIn("Number(step)===1&&win?2:1", self.source)
        self.assertIn('label:"Lệnh thắng x2"', self.worker)
        self.assertIn("step=nextHistoricalStep(step,win)", self.source)

    def test_24h_money_uses_double_step_after_step1_win(self):
        self.assertIn("function historicalMoneySettings", self.source)
        self.assertIn("function nextHistoricalStep", self.source)
        self.assertIn("Number(step)===1&&win?2:1", self.source)
        self.assertIn("const plan=historicalTradePlan(step,lossStreak,moneySettings,lossCapitalMode)", self.source)
        self.assertIn("const delta=win?plan.amount*moneySettings.payout:-plan.amount", self.source)
        self.assertIn('id="calendar24GrossWin"', self.source)
        self.assertIn('id="calendar24GrossLoss"', self.source)
        self.assertIn('id="calendar24Net"', self.source)

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
