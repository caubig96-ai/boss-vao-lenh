from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from component_selector import choose_best, evaluate_method
from database import Database
from telegram_v3 import TelegramBot

APP_VERSION = "v3.7.9"
RESULT_LABELS = {"WIN": "THẮNG", "LOSS": "THUA", None: "--"}
DIRECTION_LABELS = {"UP": "TĂNG", "DOWN": "GIẢM"}

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, db=None, telegram=None):
        self.db = db or Database()
        self.telegram = telegram or TelegramBot()

    @staticmethod
    def candle_result(direction, open_price, close_price):
        actual_direction = "UP" if close_price >= open_price else "DOWN"
        return "WIN" if direction == actual_direction else "LOSS"

    @staticmethod
    def candle_color(open_price, close_price):
        return "XANH" if close_price >= open_price else "ĐỎ"

    async def start(self):
        if self.db.conn is None:
            await self.db.connect()
        await self.db.migrate_remove_ties()
        await self.telegram.send_startup(APP_VERSION)

    async def settle_market(self, candle):
        await self.db.save_candle(candle)
        await self.db.settle_component_predictions(candle)

    async def select_component(self, forecasts, market_open_time):
        candidates = []
        for f in forecasts:
            results = await self.db.recent_component_results(f["method"], market_open_time, 100)
            candidate = evaluate_method(f.get("direction"), f.get("confidence", 0), results)
            if candidate:
                candidate["method"] = f["method"]
                candidates.append(candidate)
        return choose_best(candidates)

    async def send_selected_signal(self, selected, market_open_time):
        if not selected:
            return False
        await self.db.record_component_prediction(
            selected["method"], market_open_time,
            selected["raw_direction"], selected["sent_direction"], selected["confidence"],
        )
        await self.telegram.send_signal(selected, APP_VERSION)
        return True

    async def run_forever(self):
        await self.start()
        while True:
            await asyncio.sleep(60)


async def run():
    runtime = Runtime()
    try:
        await runtime.run_forever()
    finally:
        await runtime.db.close()
