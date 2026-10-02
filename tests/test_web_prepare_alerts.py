from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BinanceHedgeWebTests(unittest.TestCase):
    def setUp(self):
        self.web = (ROOT / "web-iphone" / "index.html").read_text(encoding="utf-8")
        self.worker = (ROOT / "cloudflare-worker" / "src" / "index.js").read_text(encoding="utf-8")

    def test_old_prediction_color_strategy_is_removed(self):
        for token in [
            "MỐC CHẴN", "MỐC LẺ", "AAA→A", "ABA→B",
            "pattern-signal", "PREDICT_API_KEY", "reverseColorMode",
            "lossCapitalMode", "pauseUntil", "SIGNAL_STEP"
        ]:
            self.assertNotIn(token, self.worker + self.web)

    def test_worker_is_binance_futures_15m_hedge(self):
        self.assertIn('const BINANCE="https://fapi.binance.com"', self.worker)
        self.assertIn('const SYMBOL="BTCUSDT"', self.worker)
        self.assertIn('const STRATEGY_VERSION="binance-15m-hedge-v1"', self.worker)
        self.assertIn("const CYCLE_SECONDS=900", self.worker)
        self.assertIn('positionSide:"LONG"', self.worker)
        self.assertIn('positionSide:"SHORT"', self.worker)

    def test_hedge_mode_is_checked_not_forced(self):
        self.assertIn('"/fapi/v1/positionSide/dual"', self.worker)
        self.assertIn("dualSidePosition!==true", self.worker)
        self.assertNotIn('POST","/fapi/v1/positionSide/dual"', self.worker)

    def test_live_config_is_secret_backed(self):
        self.assertIn("BINANCE_API_KEY", self.worker)
        self.assertIn("BINANCE_API_SECRET", self.worker)
        self.assertIn("BINANCE_LIVE_TRADING", self.worker)
        self.assertIn("HEDGE_NOTIONAL_USDT", self.worker)
        self.assertIn("HEDGE_LEVERAGE", self.worker)
        self.assertIn("HEDGE_KA", self.worker)
        self.assertIn("HEDGE_KB", self.worker)
        self.assertIn("HEDGE_BE", self.worker)

    def test_b20_b100_and_filter_match_reference_code(self):
        self.assertIn('interval:"15m"', self.worker)
        self.assertIn("const b20=bodies.slice(-20)", self.worker)
        self.assertIn("const b100=bodies.reduce", self.worker)
        self.assertIn("const a=c.ka*body.b20,b=c.kb*body.b20", self.worker)
        self.assertIn("ratio>=.8&&ratio<=2&&(a-b)>4*c.fee", self.worker)

    def test_long_short_open_together(self):
        self.assertIn('side:"BUY",positionSide:"LONG",type:"MARKET"', self.worker)
        self.assertIn('side:"SELL",positionSide:"SHORT",type:"MARKET"', self.worker)
        self.assertIn("newOrderRespType", self.worker)

    def test_tp_sl_are_close_position_orders(self):
        self.assertIn('"STOP_MARKET"', self.worker)
        self.assertIn('"TAKE_PROFIT_MARKET"', self.worker)
        self.assertIn('closePosition:"true"', self.worker)
        self.assertIn('workingType:"CONTRACT_PRICE"', self.worker)

    def test_be_moves_remaining_stop_after_original_sl(self):
        self.assertIn("moveOtherToBE", self.worker)
        self.assertIn('g.slKind!=="sl"', self.worker)
        self.assertIn("g.entry*(1+2*c.fee)", self.worker)
        self.assertIn("g.entry*(1-2*c.fee)", self.worker)
        self.assertIn('a.legs.L.why==="sl"', self.worker)
        self.assertIn('a.legs.S.why==="sl"', self.worker)

    def test_bot_never_silently_increases_notional_to_minimum(self):
        self.assertIn("const qty=stepFloor(c.notional/px,rules.stepSize)", self.worker)
        self.assertIn("qty<rules.minQty", self.worker)
        self.assertIn("Bot không tự tăng khối lượng", self.worker)
        self.assertNotIn("Math.max(rules.minQty,stepFloor", self.worker)

    def test_cycle_pnl_is_attributed_only_to_bot_order_ids(self):
        self.assertIn("cyclePnl(env,startMs,endMs,orderIds=[])", self.worker)
        self.assertIn("ids.has(Number(t.orderId))", self.worker)
        self.assertIn("orderIds:[", self.worker)
        self.assertIn("a.orderIds.push(Number(o.orderId))", self.worker)

    def test_filled_leg_cancels_its_other_trigger(self):
        self.assertIn("if(leg.tpOrderId)await cancelOrder(env,leg.tpOrderId)", self.worker)
        self.assertIn("if(leg.slOrderId)await cancelOrder(env,leg.slOrderId)", self.worker)
    def test_time_exit_after_15_minutes(self):
        self.assertIn("if(nowSec>=a.cycleEnd)", self.worker)
        self.assertIn('finishCycle(env,state,"time")', self.worker)
        self.assertIn("closePositionMarket", self.worker)

    def test_web_has_90_day_one_minute_backtest(self):
        self.assertIn("BACKTEST 90 NGÀY", self.web)
        self.assertIn("90*86400*1000", self.web)
        self.assertIn('/klines?interval=1m&limit=1500', self.web)
        self.assertIn("prepareCycles", self.web)
        self.assertIn("simulate(c,ka,kb,be,fee,slip,filt)", self.web)

    def test_backtest_grid_matches_reference_code(self):
        self.assertIn("for(const ka of [1,1.5,2,3])", self.web)
        self.assertIn("for(const kb of [.3,.5,.75,1])", self.web)
        self.assertIn("for(const be of [true,false])", self.web)
        self.assertIn("if(kb>=ka)continue", self.web)
        self.assertIn("runSet(train,ka,kb,be,.0005,.0001,true)", self.web)
        self.assertIn("runSet(test,ka,kb,be,.0005,.0001,true)", self.web)
        self.assertIn("runSet(train,ka,kb,be,0,0,true)", self.web)
        self.assertIn("rows.sort((a,b)=>b.tr.mean_bp-a.tr.mean_bp)", self.web)

    def test_web_keeps_24h_live_summary(self):
        self.assertIn("24 giờ giao dịch thực tế", self.web)
        self.assertIn('id="cycles24"', self.web)
        self.assertIn('id="wins24"', self.web)
        self.assertIn('id="loss24"', self.web)
        self.assertIn('id="pnl24"', self.web)

    def test_public_web_cannot_write_live_trading_config(self):
        self.assertNotIn("/hedge-config", self.web)
        self.assertNotIn('type="password"', self.web)
        self.assertNotIn('id="apiSecret"', self.web)


if __name__ == "__main__":
    unittest.main()
