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

    def test_strategy_version_and_tminus7_alert(self):
        self.assertIn("const SIGNAL_STEP=600", self.worker)
        self.assertIn("const ALERT_LEAD=420", self.worker)
        self.assertIn("const PAUSE_SECONDS=1800", self.worker)
        self.assertIn('STRATEGY_VERSION="alternating-lane-tminus7-v6"', self.worker)
        self.assertIn("const PREVIEW_ALERT_LEAD=420", self.source)
        self.assertIn('STRATEGY_VERSION="alternating-lane-tminus7-v6"', self.source)
        self.assertIn("remain<=450&&remain>=390", self.worker)
        self.assertIn("remain<=450&&remain>=390", self.source)

    def test_even_odd_is_based_on_minute_not_hour(self):
        self.assertIn('minute%10===0?"EVEN":"ODD"', self.worker)
        self.assertIn('return lane==="EVEN"?"MỐC CHẴN":"MỐC LẺ"', self.worker)
        self.assertIn('minute%10===0?"EVEN":"ODD"', self.source)
        self.assertIn('return lane==="EVEN"?"MỐC CHẴN":"MỐC LẺ"', self.source)
        self.assertNotIn('hour%2===0?"EVEN":"ODD"', self.worker + self.source)
        self.assertIn('evenMinuteMarks:["00","10","20","30","40","50"]', self.worker)
        self.assertIn('oddMinuteMarks:["05","15","25","35","45","55"]', self.worker)

    def test_three_color_rules(self):
        self.assertIn("function directionFromThree", self.worker)
        self.assertIn('if(a===b&&b===d)return {direction:a,patternType:"SAME"}', self.worker)
        self.assertIn('if(a===d&&a!==b)return {direction:b,patternType:"ALTERNATE"}', self.worker)

    def test_target_25_uses_55_05_15_lane(self):
        self.assertIn("return [t-3*SIGNAL_STEP,t-2*SIGNAL_STEP,t-SIGNAL_STEP]", self.worker)
        self.assertIn("decisionColors=colors.slice(1)", self.worker)
        self.assertIn("return Number(markTs)-INTERVAL", self.worker)
        self.assertIn("15:55 – 16:05 – 16:15", self.source)
        self.assertIn("16:25", self.source)

    def test_target_30_uses_00_10_20_lane(self):
        self.assertIn('exampleEven:{alert:"16:23",decisionMarks:["16:00","16:10","16:20"],targetClose:"16:30"}', self.worker)

    def test_target_is_close_mark_and_market_start_is_five_minutes_earlier(self):
        self.assertIn("marketStart:target-INTERVAL", self.worker)
        self.assertIn("targetLabelsAreCandleCloseMinutes:true", self.worker)
        self.assertIn("const marketStart=Number(pending.marketStart??(Number(pending.targetStart)-INTERVAL))", self.worker)
        self.assertIn("targetCandleFrame", self.worker)
        self.assertIn("function targetCandleFrame(mark)", self.source)

    def test_worker_can_prepare_other_lane_while_current_lane_is_live(self):
        self.assertIn("sameLanePending", self.worker)
        self.assertIn("if(sameLanePending)return", self.worker)
        self.assertNotIn("if((state.pendingOrders||[]).length)return", self.worker)
        self.assertIn("dù lệnh CHẴN :20 vẫn đang chạy", self.worker)

    def test_lane_money_steps_are_independent_and_keep_x2(self):
        self.assertIn("laneSteps:{EVEN:1,ODD:1}", self.worker)
        self.assertIn("state.laneSteps[lane]=nextStep", self.worker)
        self.assertIn("tradePlan(settings,state,lane)", self.worker)
        self.assertIn("Number(step)===1&&win?2:1", self.worker)
        self.assertIn('label:"Lệnh 2 x2"', self.worker)
        self.assertIn("independentLaneMoneySteps:true", self.worker)
        self.assertIn("calc.laneSteps?.[info.lane]", self.source)

    def test_pause_after_two_consecutive_losses(self):
        self.assertIn("consecutiveLosses:0", self.worker)
        self.assertIn("state.consecutiveLosses=win?0:Number(state.consecutiveLosses||0)+1", self.worker)
        self.assertIn("if(state.consecutiveLosses>=2)", self.worker)
        self.assertIn("PAUSE_SECONDS=1800", self.worker)
        self.assertIn("state.laneSteps={EVEN:1,ODD:1}", self.worker)
        self.assertNotIn('state.laneResults.EVEN==="LOSS"&&state.laneResults.ODD==="LOSS"', self.worker)

    def test_telegram_contains_required_context(self):
        self.assertIn('"Nến live đang chạy đóng lúc: <b>"+timeText(pending.liveCloseMark)', self.worker)
        self.assertIn('"4 màu trước: "+fourLine', self.worker)
        self.assertIn('"3 mốc chọn màu: <b>"+pending.decisionMarks.map', self.worker)
        self.assertIn('"➡️ "+buy+" cho nến <b>"+timeText(pending.targetStart)', self.worker)
        self.assertIn('"Lệnh gần nhất MỐC CHẴN: <b>"+laneResultText(previousEven)', self.worker)
        self.assertIn('MỐC LẺ: <b>"+laneResultText(previousOdd)', self.worker)

    def test_pattern_signal_previews_target_close_two_intervals_ahead(self):
        self.assertIn('u.pathname==="/pattern-signal"', self.worker)
        self.assertIn("Math.floor(nowSec/INTERVAL)*INTERVAL+2*INTERVAL", self.worker)
        self.assertIn("Math.floor(Number(nowSec)/INTERVAL)*INTERVAL+2*INTERVAL", self.source)

    def test_calendar_backtests_all_five_minute_close_marks(self):
        self.assertIn("function backtestStrategy24h", self.source)
        self.assertIn("function historicalPatternForTarget", self.source)
        self.assertIn("historicalColorAtClose", self.source)
        self.assertIn("for(const minute of [0,5,10,15,20,25,30,35,40,45,50,55])", self.source)
        self.assertIn("AAA→A / ABA→B", self.source)

    def test_calendar_uses_independent_lane_x2_and_pause(self):
        self.assertIn("const laneSteps={EVEN:1,ODD:1}", self.source)
        self.assertIn("laneSteps[lane]=step===1&&win?2:1", self.source)
        self.assertIn("consecutiveLosses=win?0:consecutiveLosses+1", self.source)
        self.assertIn("if(consecutiveLosses>=2)", self.source)
        self.assertIn("const pauseEnd=t+1800", self.source)
        self.assertIn('status:"PAUSE"', self.source)

    def test_calendar_reports_hourly_and_total_profit_pause_stats(self):
        self.assertIn('id="calendar24Pauses"', self.source)
        self.assertIn('id="calendar24PauseMinutes"', self.source)
        self.assertIn('" • Nghỉ "+rowPauseMinutes+"p"', self.source)
        self.assertIn('" • T+ "+usd24(rowGrossWin)', self.source)
        self.assertIn('" • T- $"+rowGrossLoss.toFixed(2)', self.source)
        self.assertIn('" • Net "+usd24(rowNet,true)', self.source)
        self.assertIn('calendar24PauseMinutes', self.source)

    def test_pause_resume_uses_target_market_start(self):
        self.assertIn("const targetMarketStart=targetStart-INTERVAL", self.worker)
        self.assertIn("targetMarketStart<Number(state.pauseUntil)", self.worker)
        self.assertIn("pauseActiveNow", self.worker)
        self.assertIn("patternSnapshot.paused", self.source)

    def test_result_message_and_reset_remain(self):
        self.assertIn("THẮNG LỆNH", self.worker)
        self.assertIn("THUA LỆNH", self.worker)
        self.assertIn("Lãi/lỗ lệnh này", self.worker)
        self.assertIn('u.pathname==="/trade-reset"', self.worker)
        self.assertIn("resetTradeStateAndHistory", self.source)


if __name__ == "__main__":
    unittest.main()
