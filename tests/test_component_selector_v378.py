import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import timezone
from unittest.mock import AsyncMock, patch

from component_selector import METHODS, MIN_SAMPLES, summarize, select_method, raw_direction
from database import Database
from models import Candle
from runtime_v378 import TradingSignalBotV3, SelectorTelegram


class SelectionTests(unittest.TestCase):
    """v3.7.9: selection is gated by a statistically-corrected confidence bound
    (Wilson lower bound vs. breakeven, Bonferroni-adjusted for 6x2 candidates),
    not by chasing whichever of 6 methods happens to look best this week, and
    never by the single most recent result."""

    def stats(self, **results):
        return {m: summarize(results.get(m, [])) for m in METHODS}

    def test_strong_margin_is_selected(self):
        # 35/40 wins: point estimate and lower bound both clear breakeven (0.556 @ payout .8).
        stats = self.stats(knn=['WIN'] * 35 + ['LOSS'] * 5)
        choice = select_method(dict(knn=.7), stats, payout_rate=.8)
        self.assertEqual(choice['method'], 'knn')
        self.assertEqual(choice['direction'], 'UP')
        self.assertFalse(choice['inverse'])

    def test_point_estimate_above_breakeven_is_not_enough(self):
        # 24/40 = 60% win rate clears the 55.6% breakeven on paper, but the
        # lower confidence bound (~41%) does not -- too few samples to trust it.
        stats = self.stats(knn=['WIN'] * 24 + ['LOSS'] * 16)
        self.assertIsNone(select_method(dict(knn=.7), stats, payout_rate=.8))

    def test_min_samples_gate_applies_before_confidence_check(self):
        stats = self.stats(knn=['WIN'] * 35 + ['LOSS'] * 4)  # n=39 < MIN_SAMPLES
        self.assertIsNone(select_method(dict(knn=.7), stats))
        stats['knn'] = summarize(['WIN'] * 35 + ['LOSS'] * 5)  # n=40
        self.assertIsNotNone(select_method(dict(knn=.7), stats))

    def test_losing_method_can_be_inverted_when_the_inversion_itself_clears_the_bar(self):
        # 8/40 raw wins does not qualify going forward, but losing 32/40 means
        # betting the opposite of this method's raw call wins 32/40 -- and
        # that flipped rate clears the confidence bar on its own merits.
        stats = self.stats(knn=['WIN'] * 8 + ['LOSS'] * 32)
        choice = select_method(dict(knn=.7), stats, payout_rate=.8)
        self.assertEqual(choice['method'], 'knn')
        self.assertTrue(choice['inverse'])
        self.assertEqual(choice['direction'], 'DOWN')  # raw call was UP (.7), executed flips it
        # Raw ledger must stay untouched by the inversion decision.
        self.assertEqual(stats['knn']['wins'], 8)
        self.assertEqual(stats['knn']['losses'], 32)

    def test_selection_does_not_depend_on_the_single_last_result(self):
        # The old selector required the *last* raw result to match a fixed
        # pattern before it would act. The fix depends only on the aggregate
        # win/loss history, so flipping which result happened to land last
        # must not change the outcome.
        base = ['WIN'] * 35 + ['LOSS'] * 5
        flipped = ['LOSS'] + ['WIN'] * 34 + ['LOSS'] * 5
        choice_a = select_method(dict(knn=.7), self.stats(knn=base), payout_rate=.8)
        choice_b = select_method(dict(knn=.7), self.stats(knn=flipped), payout_rate=.8)
        self.assertEqual(choice_a['method'], choice_b['method'])
        self.assertEqual(choice_a['direction'], choice_b['direction'])

    def test_best_supported_method_wins_when_several_qualify(self):
        # Both clear breakeven at payout .8 (threshold ~0.556); knn's evidence
        # is stronger (higher win rate on the same sample size), so it wins
        # even though body also technically qualifies.
        stats = self.stats(knn=['WIN'] * 35 + ['LOSS'] * 5,
                           body=['WIN'] * 30 + ['LOSS'] * 10)
        choice = select_method(dict(knn=.7, body=.7), stats, payout_rate=.8)
        self.assertEqual(choice['method'], 'knn')

    def test_neutral_invalid_probabilities_rejected(self):
        for value in [.5, .505, None, float('nan'), float('inf'), -1, 2]:
            self.assertIsNone(raw_direction(value))

    def test_summarize_window_and_tie_labels(self):
        s = summarize(['TIE', 'WIN', 'LOSS'])
        self.assertEqual(s['decided'], 2)
        self.assertIsNone(s['last'])
        self.assertEqual(s['win_rate'], .5)
        self.assertEqual(summarize(['WIN'] * 150)['wins'], 100)  # capped at WINDOW


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(':memory:')
        await self.db.open()
        b = self.bot = TradingSignalBotV3.__new__(TradingSignalBotV3)
        b.db = self.db
        b.config = SimpleNamespace(base_bet=1, max_bet=100, payout_rate=.9, timezone=timezone.utc)
        b._decision_send_lock = asyncio.Lock()
        b.decision_tasks = {}
        b.live_price = 100
        b.live_m5 = Candle('5m', 30000000, 30299999, 100, 100, 100, 100, 1, False)
        b._closed_m5_history = AsyncMock(return_value=[])
        b.signals_enabled = AsyncMock(return_value=True)
        b.telegram = SimpleNamespace(send=AsyncMock(return_value=11), detail_open_time=None)
        b.apply_money_management = AsyncMock()
        b.http = None
        await b._ensure_component_schema()

    async def asyncTearDown(self):
        await self.db.close()

    async def seed(self):
        # knn: 8 wins / 32 losses over 40 settled sessions (all before the
        # decision open_time). At payout .9 (breakeven ~52.6%), raw doesn't
        # qualify (8/40) but the inverted reading (32/40, lower bound ~62%)
        # does -- so knn should be selected with direction flipped.
        await self.db.conn.executemany('INSERT INTO component_predictions VALUES(?,?,?,?,?,?)',
            [(i * 300000, i * 300000 + 299999, 'knn', .7, 'UP',
              'WIN' if i < 8 else 'LOSS') for i in range(40)])
        await self.db.conn.commit()

    async def decide(self):
        with patch('runtime_v378.predict_next_color', return_value=SimpleNamespace(
                components={m: .7 for m in METHODS})):
            await self.bot.make_decision(30000000, 0)

    async def test_inverse_trade_win_raw_loss_and_duplicate(self):
        await self.seed()
        await self.decide()
        row = await self.bot._row_for_signal(30000000)
        self.assertEqual(row['direction'], 'DOWN')
        self.assertEqual(self.bot.telegram.send.await_count, 2)
        self.assertIn('MUA GIẢM NGAY', self.bot.telegram.send.call_args.args[0])
        # Same session must retain original choice even when toggles/history change.
        await self.db.set('inverse_signal_enabled', '1')
        await self.decide()
        self.assertEqual(self.bot.telegram.send.await_count, 2)
        c = Candle('5m', 30000000, 30299999, 100, 101, 98, 99, 1, True)
        await self.bot.settle_market(c)
        await self.bot.settle_market(c)
        row = await self.bot._row_for_signal(30000000)
        self.assertEqual(row['result'], 'WIN')
        self.assertAlmostEqual(row['pnl'], .9)
        text = await self.bot.result_text(row, 99, 'WIN', .9, 100)
        self.assertIn('Phương pháp: <b>kNN mẫu tương tự</b>', text)
        self.assertIn('Kết quả công thức gốc: <b>THUA</b>', text)
        self.assertIn('Kết quả lệnh gửi: <b>THẮNG</b>', text)
        card = await self.bot.signal_text(self.bot._prediction_from_row(row))
        self.assertIn('🔴 <b>MUA GIẢM</b>', card)
        self.assertIn('Phương pháp: <b>kNN mẫu tương tự</b>', card)
        self.assertNotIn('THỐNG KÊ GỐC', card)
        detail = await self.bot.detail_signal_text(self.bot._prediction_from_row(row))
        self.assertIn('THỐNG KÊ GỐC', detail)
        self.assertIn('Vị trí Close', detail)
        stats = await self.bot.component_stats(30300000)
        self.assertEqual(stats['knn']['wins'], 8)
        self.assertEqual(stats['knn']['losses'], 33)  # +1 from this session's own settlement
        self.assertEqual(stats['body']['losses'], 1)  # unselected methods also scored
        self.bot.apply_money_management.assert_awaited_once()

    async def test_no_buy_still_records_all_six_and_recovers(self):
        await self.decide()
        await self.decide()
        self.assertIsNone(await self.bot._row_for_signal(30000000))
        self.assertEqual(self.bot.telegram.send.await_count, 1)
        self.assertIn('KHÔNG NÊN VÀO LỆNH', self.bot.telegram.send.call_args.args[0])
        await self.db.save_candle(Candle('5m', 30000000, 30299999, 100, 101, 99, 100, 1, True))
        await self.bot.settle_pending()
        await self.bot.settle_pending()
        stats = await self.bot.component_stats(30300000)
        self.assertTrue(all(stats[m]['wins'] == 1 for m in METHODS))
        self.assertEqual(await self.db.get('bet_step', '1'), '1')

    async def test_equal_open_close_is_binary_green_not_tie(self):
        self.assertEqual(self.bot.candle_color(100, 100), 'XANH')
        self.assertEqual(self.bot.candle_result('UP', 100, 100), 'WIN')
        self.assertEqual(self.bot.candle_result('DOWN', 100, 100), 'LOSS')

    async def test_no_lookahead_and_reset(self):
        await self.seed()
        stats = await self.bot.component_stats(300000)
        self.assertEqual(stats['knn']['decided'], 1)
        await self.db.set('stats_reset_at', '12000000')  # past the seeded window's last open_time
        self.assertEqual((await self.bot.component_stats(30000000))['knn']['decided'], 0)

    async def test_old_toggle_disabled(self):
        await self.bot.handle_telegram('callback', 'toggle_inverse_signal', {})
        self.assertEqual(await self.db.get('inverse_signal_enabled', '0'), '0')
        t = SelectorTelegram('token', '1', AsyncMock())
        callbacks = [b['callback_data'] for row in t.keyboard()['inline_keyboard'] for b in row]
        self.assertNotIn('toggle_inverse_signal', callbacks)

    def test_legacy_desktop_entrypoint_stays_available(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn('from runtime_v378 import APP_VERSION, TradingSignalBotV3',
                      (root / 'desktop_v378.pyw').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
