import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import timezone
from unittest.mock import AsyncMock, patch

from component_selector import METHODS, summarize, select_method, raw_direction
from database import Database
from models import Candle
from runtime_v378 import TradingSignalBotV3, SelectorTelegram


class SelectionTests(unittest.TestCase):
    def stats(self, **results):
        return {m: summarize(results.get(m, [])) for m in METHODS}

    def test_raw_win_priority_and_last_loss(self):
        stats = self.stats(knn=['LOSS'] * 9 + ['WIN'] * 21,
                           body=['LOSS'] * 12 + ['WIN'] * 18)
        self.assertEqual(select_method(dict(knn=.7, body=.3), stats)['method'], 'knn')
        stats['knn']['last'] = 'WIN'
        self.assertEqual(select_method(dict(knn=.7, body=.3), stats)['method'], 'body')

    def test_losing_method_inverts_without_mutating_stats(self):
        stats = self.stats(knn=['WIN'] * 6 + ['LOSS'] * 24,
                           body=['LOSS'] * 9 + ['WIN'] * 21)
        choice = select_method(dict(knn=.7, body=.7), stats)
        self.assertEqual(choice['method'], 'knn')
        self.assertEqual(choice['direction'], 'DOWN')
        self.assertEqual(stats['knn']['losses'], 24)
        stats['knn']['last'] = 'LOSS'
        self.assertEqual(select_method(dict(knn=.7, body=.7), stats)['method'], 'body')

    def test_fifty_fifty_and_sample_gate(self):
        stats = self.stats(knn=['LOSS'] * 5 + ['WIN'] * 5)
        self.assertIsNone(select_method(dict(knn=.7), stats))
        self.assertEqual(select_method(dict(knn=.7), stats, min_samples=10)['direction'], 'UP')
        stats['knn']['last'] = 'WIN'
        self.assertIsNone(select_method(dict(knn=.7), stats, min_samples=10))

    def test_neutral_invalid_and_ties(self):
        for value in [.5, .505, None, float('nan'), float('inf'), -1, 2]:
            self.assertIsNone(raw_direction(value))
        s = summarize(['TIE', 'WIN', 'LOSS'])
        self.assertEqual(s['decided'], 2)
        self.assertEqual(s['last'], 'TIE')
        self.assertEqual(s['win_rate'], .5)

    def test_window_and_stable_tie_break(self):
        self.assertEqual(summarize(['WIN'] * 100 + ['LOSS'] * 100)['losses'], 0)
        stats = self.stats(knn=['LOSS'] * 9 + ['WIN'] * 21,
                           body=['LOSS'] * 9 + ['WIN'] * 21)
        self.assertEqual(select_method(dict(knn=.6, body=.6), stats)['method'], 'knn')


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
        await self.db.conn.executemany('INSERT INTO component_predictions VALUES(?,?,?,?,?,?)',
            [(i * 300000, i * 300000 + 299999, 'knn', .7, 'UP',
              'WIN' if i >= 24 else 'LOSS') for i in range(30)])
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
        self.assertEqual(stats['knn']['wins'], 6)
        self.assertEqual(stats['knn']['losses'], 25)
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
        self.assertTrue(all(stats[m]['ties'] == 1 for m in METHODS))
        self.assertEqual(await self.db.get('bet_step', '1'), '1')

    async def test_no_lookahead_and_reset(self):
        await self.seed()
        stats = await self.bot.component_stats(300000)
        self.assertEqual(stats['knn']['decided'], 1)
        await self.db.set('stats_reset_at', '9000000')
        self.assertEqual((await self.bot.component_stats(30000000))['knn']['decided'], 0)

    async def test_old_toggle_disabled(self):
        await self.bot.handle_telegram('callback', 'toggle_inverse_signal', {})
        self.assertEqual(await self.db.get('inverse_signal_enabled', '0'), '0')
        t = SelectorTelegram('token', '1', AsyncMock())
        callbacks = [b['callback_data'] for row in t.keyboard()['inline_keyboard'] for b in row]
        self.assertNotIn('toggle_inverse_signal', callbacks)

    def test_platform_entrypoints_match(self):
        root = Path(__file__).resolve().parents[1]
        for name in ['cloud_v3.py', 'desktop_v378.pyw']:
            self.assertIn('from runtime_v378 import APP_VERSION, TradingSignalBotV3',
                          (root / name).read_text(encoding='utf-8'))
        self.assertIn('desktop_v378.pyw', (root / 'build_windows.bat').read_text())
