from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone

import aiosqlite

from models import Candle, Prediction


log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candles (
 interval TEXT NOT NULL, open_time INTEGER NOT NULL, close_time INTEGER NOT NULL,
 open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
 volume REAL NOT NULL, PRIMARY KEY(interval, open_time)
);
CREATE TABLE IF NOT EXISTS signals (
 market_open_time INTEGER PRIMARY KEY, market_close_time INTEGER NOT NULL,
 target_price REAL NOT NULL, signal_price REAL NOT NULL, direction TEXT NOT NULL,
 confidence REAL NOT NULL, m1_probability REAL NOT NULL, m5_probability REAL NOT NULL,
 pattern_samples INTEGER NOT NULL, bet_amount REAL NOT NULL, bet_step INTEGER NOT NULL,
 actual INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', result TEXT,
 close_price REAL, pnl REAL DEFAULT 0, telegram_message_id INTEGER,
 created_at TEXT NOT NULL, settled_at TEXT
);
CREATE TABLE IF NOT EXISTS bot_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, payload TEXT NOT NULL,
 created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    def _migrate_legacy_windows_database(self) -> None:
        """Một lần chuyển DB cũ cạnh EXE sang LOCALAPPDATA để rebuild không mất thống kê."""
        if os.name != "nt":
            return
        target = os.path.abspath(self.path)
        if os.path.exists(target):
            return
        candidates = [
            os.path.abspath(os.path.join(os.getcwd(), "data", "bot.db")),
            os.path.abspath(os.path.join(os.path.dirname(sys.executable), "data", "bot.db")),
        ]
        seen: set[str] = set()
        for source in candidates:
            if source in seen or source == target:
                continue
            seen.add(source)
            if not os.path.isfile(source):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
            for suffix in ("-wal", "-shm"):
                sidecar = source + suffix
                if os.path.isfile(sidecar):
                    shutil.copy2(sidecar, target + suffix)
            log.info("Đã chuyển dữ liệu thống kê cũ từ %s sang %s", source, target)
            return

    async def open(self) -> None:
        self._migrate_legacy_windows_database()
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def set_default(self, key: str, value: str) -> None:
        await self.conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))
        await self.conn.commit()

    async def set(self, key: str, value: object) -> None:
        await self.conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        await self.conn.commit()

    async def get(self, key: str, default: str = "") -> str:
        row = await (await self.conn.execute("SELECT value FROM settings WHERE key=?", (key,))).fetchone()
        return row["value"] if row else default

    async def save_candle(self, candle: Candle) -> None:
        if not candle.closed:
            return
        await self.conn.execute(
            """INSERT INTO candles VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(interval,open_time) DO UPDATE SET close_time=excluded.close_time,
               open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume""",
            (candle.interval, candle.open_time, candle.close_time, candle.open, candle.high,
             candle.low, candle.close, candle.volume),
        )
        await self.conn.commit()

    async def create_signal(self, p: Prediction) -> bool:
        cursor = await self.conn.execute(
            """INSERT OR IGNORE INTO signals(
               market_open_time,market_close_time,target_price,signal_price,direction,confidence,
               m1_probability,m5_probability,pattern_samples,bet_amount,bet_step,actual,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (p.market_open_time, p.market_close_time, p.target_price, p.signal_price, p.direction,
             p.confidence, p.m1_probability, p.m5_probability, p.pattern_samples, p.bet_amount,
             p.bet_step, int(p.actual), datetime.now(timezone.utc).isoformat()),
        )
        await self.conn.commit()
        return cursor.rowcount == 1

    async def update_message_id(self, open_time: int, message_id: int) -> None:
        await self.conn.execute("UPDATE signals SET telegram_message_id=? WHERE market_open_time=?", (message_id, open_time))
        await self.conn.commit()

    async def pending(self) -> list[aiosqlite.Row]:
        return await (await self.conn.execute("SELECT * FROM signals WHERE status='PENDING' ORDER BY market_open_time" )).fetchall()

    async def settle(self, open_time: int, result: str, close_price: float, pnl: float) -> None:
        await self.conn.execute(
            "UPDATE signals SET status='SETTLED',result=?,close_price=?,pnl=?,settled_at=? WHERE market_open_time=?",
            (result, close_price, pnl, datetime.now(timezone.utc).isoformat(), open_time),
        )
        await self.conn.commit()

    async def stats(self, start_ms: int, actual_only: bool) -> dict:
        condition = "AND actual=1" if actual_only else ""
        row = await (await self.conn.execute(
            f"""SELECT COUNT(*) total,
                 SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) wins,
                 SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) losses,
                 SUM(CASE WHEN result='TIE' THEN 1 ELSE 0 END) ties,
                 COALESCE(SUM(bet_amount),0) staked, COALESCE(SUM(pnl),0) pnl
                 FROM signals WHERE market_open_time>=? AND status='SETTLED' {condition}""", (start_ms,)
        )).fetchone()
        return dict(row)

    async def confidence_stats(self, start_ms: int, actual_only: bool = False) -> dict[str, dict]:
        """Win/loss by the same confidence bands used in Telegram.

        Ties are reported separately and are not included in the win-rate denominator.
        By default this uses every settled analysis signal so the buckets keep learning
        even while real Telegram sending is paused.
        """
        condition = "AND actual=1" if actual_only else ""
        rows = await (await self.conn.execute(
            f"""SELECT
                    CASE
                        WHEN confidence < 0.57 THEN 'LOW'
                        WHEN confidence < 0.65 THEN 'MEDIUM'
                        ELSE 'HIGH'
                    END AS bucket,
                    SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN result='TIE' THEN 1 ELSE 0 END) AS ties
                 FROM signals
                 WHERE market_open_time>=? AND status='SETTLED' {condition}
                 GROUP BY bucket""",
            (start_ms,),
        )).fetchall()

        result = {
            "LOW": {"wins": 0, "losses": 0, "ties": 0},
            "MEDIUM": {"wins": 0, "losses": 0, "ties": 0},
            "HIGH": {"wins": 0, "losses": 0, "ties": 0},
        }
        for row in rows:
            result[row["bucket"]] = {
                "wins": int(row["wins"] or 0),
                "losses": int(row["losses"] or 0),
                "ties": int(row["ties"] or 0),
            }
        for stats in result.values():
            decided = stats["wins"] + stats["losses"]
            stats["decided"] = decided
            stats["total"] = decided + stats["ties"]
            stats["win_rate"] = (stats["wins"] / decided * 100.0) if decided else 0.0
        return result

    async def event(self, event_type: str, payload: dict) -> None:
        await self.conn.execute(
            "INSERT INTO bot_events(event_type,payload,created_at) VALUES(?,?,?)",
            (event_type, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )
        await self.conn.commit()
