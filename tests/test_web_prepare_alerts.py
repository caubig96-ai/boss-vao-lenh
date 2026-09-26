from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebPrepareAlertsTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "web-iphone" / "index.html").read_text(encoding="utf-8")
        self.worker = (ROOT / "cloudflare-worker" / "src" / "index.js").read_text(encoding="utf-8")

    def test_exact_8_image_groups_are_active(self):
        self.assertIn("Boss 8 Nhóm", self.source)
        expected = ["RGRR","GRGR","RRGR","GGRR","RGRG","GRGG","RRGG","GGRG"]
        for item in expected:
            self.assertIn(item, self.source)
            self.assertIn(item, self.worker)
        self.assertIn('RGR:"R"', self.worker)
        self.assertIn('GRG:"G"', self.worker)
        self.assertIn('RRG:"R"', self.worker)
        self.assertIn('GGR:"G"', self.worker)
        self.assertNotIn("Boss 12 Mẫu", self.source)
        self.assertNotIn("image-12", self.source)
        self.assertNotIn("image-12", self.worker)

    def test_recognition_uses_only_three_closed_candles(self):
        self.assertIn("function latestClosed3", self.source)
        self.assertIn('const code=closed3.map(x=>x.c).join("");', self.source)
        self.assertNotIn('join("")+liveColor', self.source)
        self.assertIn("nến live hiện tại không tham gia chọn màu", self.source)
        self.assertIn('RGR:"R"', self.worker)
        self.assertIn('GRG:"G"', self.worker)

    def test_entry_alert_fires_once_at_one_minute_for_next_frame(self):
        self.assertIn("remain<=60&&remain>30", self.source)
        self.assertNotIn("remain<=30&&remain>0", self.source)
        self.assertIn("CÒN 1 PHÚT • VÀO LỆNH PHIÊN SAU", self.source)
        self.assertIn("prepare_60_start", self.source)
        self.assertIn("CÒN ~1 PHÚT • BÁO LỆNH PHIÊN SAU", self.worker)
        self.assertIn("schedulePrepareAt60", self.worker)
        self.assertIn("if(remain>70||remain<=45)return", self.worker)

    def test_latest_two_results_control_follow_or_reverse(self):
        self.assertIn("const recent100=settledSignals(rounds).slice(-100)", self.worker)
        self.assertIn("sameGroup.slice(-2).reverse()", self.worker)
        self.assertIn('pair==="V-V"', self.worker)
        self.assertIn('pair==="X-X"', self.worker)
        self.assertIn('pair==="V-X"', self.worker)
        self.assertIn('"REVERSE_XV"', self.worker)
        self.assertIn("function recentTwoDecision", self.source)
        self.assertIn("rawPatternSettled().slice(-100)", self.source)
        self.assertIn("sameGroup.slice(-2).reverse()", self.source)
        self.assertIn("2 kết quả gần nhất", self.source)

    def test_two_losses_pause_signals_for_15_minutes(self):
        self.assertIn("lossStreak", self.worker)
        self.assertIn("state.pauseUntil=nowSec+15*60", self.worker)
        self.assertIn("TẠM DỪNG BÁO LỆNH 15 PHÚT", self.worker)
        self.assertIn("Number(state.pauseUntil||0)>nowSec", self.worker)
        self.assertIn("cloudTradeState?.pauseUntil", self.source)

    def test_result_message_reports_win_loss_and_money(self):
        self.assertIn("THẮNG LỆNH", self.worker)
        self.assertIn("THUA LỆNH", self.worker)
        self.assertIn("Lãi/lỗ lệnh này", self.worker)
        self.assertIn("Tổng lãi/lỗ sau reset", self.worker)
        self.assertIn("Số dư theo dõi", self.worker)
        self.assertIn("maybeSendSettlement", self.worker)

    def test_pattern_history_uses_three_candles_skips_live_then_scores_next(self):
        self.assertIn("for(let i=2;i<rounds.length;i++)", self.source)
        self.assertIn("const w=rounds.slice(i-2,i+1)", self.source)
        self.assertIn("const targetT=w[2].t+2*INTERVAL", self.source)
        self.assertIn("for(let i=2;i<rounds.length;i++)", self.worker)
        self.assertIn("w[2].t+2*INTERVAL", self.worker)

    def test_24h_calendar_is_24_hours_by_12_slots_and_uses_adaptive_results(self):
        self.assertIn("Lịch 24 giờ theo nhóm màu nến", self.source)
        self.assertIn("24 hàng giờ", self.source)
        self.assertIn("12 ô × 5 phút", self.source)
        self.assertIn("for(let i=0;i<288;i++)", self.source)
        self.assertIn("for(let row=0;row<24;row++)", self.source)
        self.assertIn("slice(row*12,row*12+12)", self.source)
        self.assertIn("function buildAdaptiveHistory", self.source)
        self.assertIn("adaptiveDecisionFromPrior", self.source)
        self.assertIn('status:win?"WIN":"LOSS"', self.source)
        self.assertIn('sum.textContent="V "+rowW+" • X "+rowL+" • · "+rowN', self.source)

    def test_cloud_reset_and_history_refresh(self):
        self.assertIn("function rawPatternSettled", self.source)
        self.assertIn("resetTradeStateAndHistory", self.source)
        self.assertIn('fetch(CLOUD+"/trade-reset"', self.source)
        self.assertIn('body:JSON.stringify({confirm:"RESET"})', self.source)
        self.assertNotIn("Kết quả lệnh thực tế hôm nay", self.source)
        self.assertNotIn("Lệnh Telegram hôm nay", self.source)
        self.assertNotIn("todayToolHistory", self.source)
        self.assertIn('u.pathname==="/trade-reset"', self.worker)

    def test_auto_start_loads_cloud_history(self):
        self.assertIn("async function autoStart", self.source)
        self.assertIn("fetchCloudHistory(false)", self.source)
        self.assertIn("async function ensureHistory100", self.source)
        self.assertIn("setTimeout(autoStart,100)", self.source)
        self.assertIn("slice(-6000)", self.source)

    def test_browser_vibration_is_best_effort(self):
        self.assertIn("navigator.vibrate", self.source)

    def test_ios_requires_manual_audio_activation(self):
        self.assertIn("BẬT CẢNH BÁO", self.source)
        self.assertIn("AudioContext", self.source)


if __name__ == "__main__":
    unittest.main()
