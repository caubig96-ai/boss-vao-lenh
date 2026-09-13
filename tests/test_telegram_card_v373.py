from __future__ import annotations

import asyncio
import inspect
import unittest
from types import SimpleNamespace

import aiosqlite

from runtime_v373 import (
    APP_VERSION,
    COLOR_ENTRY_MIN_AGREEMENT,
    CompactTelegramBotV373,
    TradingSignalBotV3,
    recommend_from_agreement,
)


async def _noop_handler(*_args, **_kwargs):
    return None


class FakeDB:
    def __init__(self, conn):
        self.conn = conn

    async def set(self, key, value):
        await self.conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(key), str(value)),
        )
        await self.conn.commit()


class V373PureTests(unittest.TestCase):
    def test_version_and_entry_rule(self):
        self.assertEqual(APP_VERSION, "3.7.3")
        self.assertEqual(COLOR_ENTRY_MIN_AGREEMENT, 3)
        self.assertFalse(recommend_from_agreement(SimpleNamespace(agreement=2)))
        self.assertTrue(recommend_from_agreement(SimpleNamespace(agreement=3)))
        self.assertTrue(recommend_from_agreement(SimpleNamespace(agreement=6)))

    def test_keyboard_has_no_mode_selector(self):
        telegram = CompactTelegramBotV373("token", "1", _noop_handler)
        rows = telegram.keyboard(True)["inline_keyboard"]
        callbacks = [button["callback_data"] for row in rows for button in row]
        self.assertNotIn("analysis_mode", callbacks)
        self.assertIn("threshold_stats", callbacks)
        self.assertIn("status", callbacks)

    def test_signal_card_source_drops_old_title_and_adds_requested_fields(self):
        source = inspect.getsource(TradingSignalBotV3.signal_text)
        self.assertNotIn("TÍN HIỆU M5", source)
        self.assertIn("Phân tích cùng hướng", source)
        self.assertIn("Nến trước", source)


class V373AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_detail_button_does_not_depend_on_old_title(self):
        telegram = CompactTelegramBotV373("token", "1", _noop_handler)
        telegram.detail_open_time = 123456
        captured = {}

        async def fake_call(method, payload):
            captured["method"] = method
            captured["payload"] = payload
            return {"message_id": 77}

        telegram._call = fake_call  # type: ignore[method-assign]
        message_id = await telegram.send("🟢 <b>MUA TĂNG</b>")
        self.assertEqual(message_id, 77)
        rows = captured["payload"]["reply_markup"]["inline_keyboard"]
        self.assertEqual(rows[0][0]["callback_data"], "detail_123456")
        callbacks = [button["callback_data"] for row in rows for button in row]
        self.assertNotIn("analysis_mode", callbacks)

    async def test_primary_claim_is_atomic_for_same_m5(self):
        conn = await aiosqlite.connect(":memory:")
        try:
            await conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            await conn.commit()
            fake = SimpleNamespace(db=FakeDB(conn))
            claims = await asyncio.gather(*[
                TradingSignalBotV3._claim_signal_message(fake, 1_700_000_000_000)
                for _ in range(8)
            ])
            self.assertEqual(sum(bool(value) for value in claims), 1)
        finally:
            await conn.close()


if __name__ == "__main__":
    unittest.main()
