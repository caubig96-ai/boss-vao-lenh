from __future__ import annotations

import asyncio
from dataclasses import dataclass

from models import Candle


@dataclass
class BaseRuntime:
    db: object = None

    async def settle_market(self, candle: Candle):
        if self.db:
            await self.db.save_candle(candle)
            await self.db.settle_component_predictions(candle)

    async def run_forever(self):
        while True:
            await asyncio.sleep(60)
