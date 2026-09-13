from __future__ import annotations

import aiosqlite
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    interval TEXT NOT NULL,
    open_time INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    PRIMARY KEY(interval, open_time)
);
CREATE TABLE IF NOT EXISTS component_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method TEXT NOT NULL,
    market_open_time INTEGER NOT NULL,
    raw_direction TEXT,
    sent_direction TEXT,
    confidence REAL,
    result TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_component_predictions_method_time
ON component_predictions(method, market_open_time DESC);
CREATE TABLE IF NOT EXISTS color_predictions (
    market_open_time INTEGER PRIMARY KEY,
    direction TEXT NOT NULL,
    confidence REAL,
    status TEXT DEFAULT 'PENDING',
    result TEXT,
    actual_color TEXT,
    settled_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Database:
    def __init__(self, path="boss_vao_lenh.db"):
        self.path = path
        self.conn = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()
        return self

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def save_candle(self, candle):
        await self.conn.execute(
            """INSERT OR REPLACE INTO candles(interval,open_time,open,high,low,close)
               VALUES(?,?,?,?,?,?)""",
            (candle.interval, candle.open_time, candle.open, candle.high, candle.low, candle.close),
        )
        await self.conn.commit()

    async def record_component_prediction(self, method, market_open_time, raw_direction, sent_direction, confidence):
        await self.conn.execute(
            """INSERT INTO component_predictions(method,market_open_time,raw_direction,sent_direction,confidence)
               VALUES(?,?,?,?,?)""",
            (method, market_open_time, raw_direction, sent_direction, confidence),
        )
        await self.conn.commit()

    async def recent_component_results(self, method, before_open_time=None, limit=100):
        sql = "SELECT result FROM component_predictions WHERE method=? AND result IN ('WIN','LOSS')"
        params = [method]
        if before_open_time is not None:
            sql += " AND market_open_time < ?"
            params.append(before_open_time)
        sql += " ORDER BY market_open_time DESC LIMIT ?"
        params.append(limit)
        cur = await self.conn.execute(sql, params)
        rows = await cur.fetchall()
        return [r["result"] for r in rows]

    async def settle_component_predictions(self, candle):
        if candle.interval != "5m":
            return
        actual = "UP" if candle.close >= candle.open else "DOWN"
        await self.conn.execute(
            """UPDATE component_predictions
               SET result=CASE WHEN raw_direction=? THEN 'WIN' ELSE 'LOSS' END
               WHERE market_open_time=? AND raw_direction IN ('UP','DOWN')
                 AND (result IS NULL OR result='TIE')""",
            (actual, candle.open_time),
        )
        await self.conn.commit()

    async def migrate_remove_ties(self):
        await self.conn.execute(
            """UPDATE component_predictions AS p SET result=(
                 SELECT CASE WHEN (p.raw_direction='UP')=(c.close>=c.open) THEN 'WIN' ELSE 'LOSS' END
                 FROM candles c WHERE c.interval='5m' AND c.open_time=p.market_open_time)
               WHERE result='TIE' AND raw_direction IN ('UP','DOWN') AND EXISTS(
                 SELECT 1 FROM candles c WHERE c.interval='5m' AND c.open_time=p.market_open_time)"""
        )
        await self.conn.commit()
