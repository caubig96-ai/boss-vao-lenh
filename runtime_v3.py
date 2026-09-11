from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sqlite3
import sys
import time
from collections import deque
from contextlib import closing
from datetime import datetime, time as dt_time, timezone
from pathlib import Path

import aiohttp

from config import Config
from database import Database
from indicators import (
    ANALYSIS_MODES,
    all_mode_predictions,
    analysis_mode_label,
    blended_prediction,
    candle_analysis,
    normalize_analysis_mode,
)
from models import Candle, Prediction
from telegram_v3 import TelegramBotV3

APP_VERSION = "3.2.0"
BINANCE_REST = "https://fapi.binance.com"
BINANCE_WS = "wss://fstream.binance.com/stream"
M1_24H = 1440
M5_24H = 288
WS_STALE_SECONDS = 2.5
REST_STALE_SECONDS = 3.5
log = logging.getLogger("boss-vao-lenh-v3")


def _windows_persistent_db() -> Path:
    root = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
    return Path(root) / "BossVaoLenh" / "data" / "bot.db"


def resolve_database_path(config: Config) -> Path:
    """On Windows always use one durable DB, ignoring legacy relative DATABASE_PATH=data/bot.db."""
    if os.name == "nt":
        return _windows_persistent_db()
    configured = Path(config.database_path)
    return configured if configured.is_absolute() else Path.cwd() / configured


def _signal_count(path: Path) -> int:
    try:
        with closing(sqlite3.connect(path, timeout=1)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM signals").fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def migrate_legacy_database(target: Path, configured_path: str = "") -> Path | None:
    """Recover the richest legacy DB into the durable LocalAppData location.

    V2 could already have created an empty target DB, so existence alone is not
    proof that it contains the user's history. If the target has zero signals and
    a legacy DB has history, replace the empty target. Otherwise preserve target.
    """
    if os.name != "nt":
        return None

    cwd = Path.cwd().resolve()
    exe_dir = Path(sys.executable).resolve().parent
    candidates = [
        cwd / "data" / "bot.db",
        cwd.parent / "data" / "bot.db",
        exe_dir / "data" / "bot.db",
        exe_dir.parent / "data" / "bot.db",
    ]
    if configured_path:
        configured = Path(configured_path)
        if configured.is_absolute():
            candidates.append(configured)
        else:
            candidates.extend([cwd / configured, cwd.parent / configured, exe_dir / configured, exe_dir.parent / configured])

    unique: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        try:
            key = str(item.resolve())
        except OSError:
            key = str(item)
        if key in seen or item == target or not item.is_file():
            continue
        seen.add(key)
        unique.append(item)
    if not unique:
        return None

    source = max(unique, key=lambda p: (_signal_count(p), p.stat().st_mtime))
    source_count = _signal_count(source)
    target_count = _signal_count(target) if target.is_file() else 0

    if target.is_file() and target_count > 0:
        return None
    if target.is_file() and target_count == 0 and source_count == 0:
        return None

    target.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        stale = Path(str(target) + suffix)
        try:
            if stale.exists():
                stale.unlink()
        except OSError:
            pass
    try:
        with closing(sqlite3.connect(source, timeout=3)) as src, closing(sqlite3.connect(target, timeout=3)) as dst:
            src.backup(dst)
            dst.commit()
    except sqlite3.Error:
        shutil.copy2(source, target)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(source) + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, Path(str(target) + suffix))
    log.info("Recovered legacy database %s (%d signals) -> %s", source, source_count, target)
    return source


class TradingSignalBotV3:
    def __init__(self, config: Config):
        self.config = config
        self.database_path = resolve_database_path(config)
        migrate_legacy_database(self.database_path, config.database_path)
        self.db = Database(str(self.database_path))
        self.telegram = TelegramBotV3(config.telegram_token, config.telegram_chat_id, self.handle_telegram, self._save_telegram_offset)
        self.http: aiohttp.ClientSession | None = None
        self.m1: deque[Candle] = deque(maxlen=M1_24H)
        self.m5: deque[Candle] = deque(maxlen=M5_24H)
        self.live_m1: Candle | None = None
        self.live_m5: Candle | None = None
        self.live_price = 0.0
        self.trade_ticks = 0
        self.ws_connected = False
        self.ws_reconnects = 0
        self.rest_fallback_hits = 0
        self.last_market_error = ""
        self.last_any_rx_mono = 0.0
        self.last_trade_rx_mono = 0.0
        self.last_kline_rx_mono = 0.0
        self.last_rest_ok_mono = 0.0
        self.last_trade_time_ms = 0
        self.last_market_event_ms = 0
        self.server_offset_ms = 0
        self.decision_tasks: dict[int, asyncio.Task] = {}
        self.last_decision_open = 0
        self.last_decision_state = "CHƯA CÓ"
        self.stop_event = asyncio.Event()

    def server_now_ms(self) -> int:
        return int(time.time() * 1000) + int(self.server_offset_ms)

    def _age(self, stamp: float) -> float | None:
        return None if stamp <= 0 else max(0.0, time.monotonic() - stamp)

    async def _save_telegram_offset(self, offset: int) -> None:
        if self.db.conn:
            await self.db.set("telegram_update_offset", offset)

    async def setup(self) -> None:
        await self.db.open()
        await self.db.conn.execute("PRAGMA journal_mode=WAL")
        await self.db.conn.execute("PRAGMA synchronous=NORMAL")
        await self.db.conn.execute("PRAGMA busy_timeout=5000")
        await self.db.conn.commit()
        for key, value in (
            ("manual_enabled", "1"), ("risk_pause_until", "0"), ("risk_cycle_losses", "0"),
            ("base_bet", str(self.config.base_bet)), ("payout_rate", str(self.config.payout_rate)),
            ("bet_step", "1"), ("current_balance", "0"), ("pause_started_at", "0"),
            ("awaiting_setbet", "0"), ("stats_reset_at", "0"), ("telegram_update_offset", "0"),
            ("analysis_mode", "AUTO"),
        ):
            await self.db.set_default(key, value)

        timeout = aiohttp.ClientTimeout(total=20, connect=8, sock_read=15)
        self.http = aiohttp.ClientSession(timeout=timeout)
        await self.telegram.open()
        try:
            self.telegram.offset = int(await self.db.get("telegram_update_offset", "0"))
        except ValueError:
            self.telegram.offset = 0
        if self.telegram.offset <= 0:
            await self.telegram.bootstrap_offset()

        try:
            await self.sync_server_time()
        except Exception as exc:
            self.last_market_error = f"server time: {exc}"
        try:
            await self.backfill()
        except Exception as exc:
            self.last_market_error = f"backfill: {exc}"
            log.exception("Initial backfill failed; continuing with live supervisors")
        try:
            await self.settle_pending()
        except Exception:
            log.exception("Initial settle_pending failed; continuing")

    async def close(self) -> None:
        for task in list(self.decision_tasks.values()):
            task.cancel()
        await self.telegram.close()
        if self.http and not self.http.closed:
            await self.http.close()
        await self.db.close()

    async def sync_server_time(self) -> None:
        if not self.http:
            return
        t0 = int(time.time() * 1000)
        async with self.http.get(f"{BINANCE_REST}/fapi/v1/time") as response:
            response.raise_for_status()
            payload = await response.json()
        t1 = int(time.time() * 1000)
        midpoint = (t0 + t1) // 2
        self.server_offset_ms = int(payload["serverTime"]) - midpoint

    async def _recent_closed_klines(self, interval: str, count: int) -> list[list]:
        if not self.http:
            return []
        now_ms = self.server_now_ms()
        end_time = now_ms - 1
        result: list[list] = []
        while len(result) < count:
            remaining = count - len(result)
            params = {"symbol": self.config.symbol, "interval": interval, "limit": min(1000, remaining), "endTime": end_time}
            async with self.http.get(f"{BINANCE_REST}/fapi/v1/klines", params=params) as response:
                response.raise_for_status()
                rows = await response.json()
            closed_rows = [row for row in rows if int(row[6]) < now_ms]
            if not closed_rows:
                break
            result = closed_rows + result
            end_time = int(closed_rows[0][0]) - 1
            if len(rows) < int(params["limit"]):
                break
        return result[-count:]

    async def backfill(self) -> None:
        for interval, target, count in (("1m", self.m1, M1_24H), ("5m", self.m5, M5_24H)):
            rows = await self._recent_closed_klines(interval, count)
            if not rows:
                continue
            target.clear()
            for row in rows:
                candle = Candle.from_rest(interval, row)
                target.append(candle)
                await self.db.save_candle(candle)
        log.info("24h history ready: M1=%d M5=%d", len(self.m1), len(self.m5))

    def _mark_rx(self, kind: str) -> None:
        now = time.monotonic()
        self.last_any_rx_mono = now
        if kind == "trade":
            self.last_trade_rx_mono = now
        elif kind == "kline":
            self.last_kline_rx_mono = now

    def _apply_trade_to_live(self, interval: str, trade_time_ms: int, price: float) -> bool:
        attr = "live_m1" if interval == "1m" else "live_m5"
        current: Candle | None = getattr(self, attr)
        bucket = Candle.bucket_open_time(interval, trade_time_ms)
        if current is not None and bucket < current.open_time:
            return False
        if current is None or bucket > current.open_time:
            updated = Candle.from_trade(interval, trade_time_ms, price)
            is_new = True
        elif current.closed:
            return False
        else:
            updated = current.with_trade(price)
            is_new = False
        setattr(self, attr, updated)
        return is_new

    def _merge_live_kline(self, candle: Candle) -> Candle:
        attr = "live_m1" if candle.interval == "1m" else "live_m5"
        current: Candle | None = getattr(self, attr)
        if candle.closed or current is None or current.open_time != candle.open_time:
            return candle
        return Candle(
            candle.interval, candle.open_time, candle.close_time, candle.open,
            max(candle.high, current.high), min(candle.low, current.low),
            current.close if self.last_trade_rx_mono >= self.last_kline_rx_mono else candle.close,
            candle.volume, False,
        )

    async def handle_market_message(self, data: dict) -> None:
        event = data.get("e")
        event_time_ms = int(data.get("E") or self.server_now_ms())
        self.last_market_event_ms = max(self.last_market_event_ms, event_time_ms)
        observed_offset = event_time_ms - int(time.time() * 1000)
        if abs(observed_offset - self.server_offset_ms) > 500:
            self.server_offset_ms = observed_offset

        if event == "aggTrade":
            self._mark_rx("trade")
            trade_time_ms = int(data.get("T") or event_time_ms)
            if trade_time_ms < self.last_trade_time_ms:
                return
            price = float(data["p"])
            self.last_trade_time_ms = trade_time_ms
            self.trade_ticks += 1
            self.live_price = price
            self._apply_trade_to_live("1m", trade_time_ms, price)
            new_m5 = self._apply_trade_to_live("5m", trade_time_ms, price)
            if new_m5 and self.live_m5:
                self.schedule_decision(self.live_m5, event_time_ms)
            return

        if event != "kline":
            return
        self._mark_rx("kline")
        raw = Candle.from_ws(data)
        attr = "live_m1" if raw.interval == "1m" else "live_m5"
        current: Candle | None = getattr(self, attr)
        if current is None or raw.open_time >= current.open_time:
            setattr(self, attr, self._merge_live_kline(raw))
        trade_age = self._age(self.last_trade_rx_mono)
        if self.live_price <= 0 or trade_age is None or trade_age > 1.0:
            self.live_price = raw.close
        if raw.interval == "5m":
            self.schedule_decision(getattr(self, attr), event_time_ms)
        if raw.closed:
            await self._store_closed(raw)

    async def _store_closed(self, candle: Candle) -> None:
        target = self.m1 if candle.interval == "1m" else self.m5
        if not target or target[-1].open_time < candle.open_time:
            target.append(candle)
        elif target[-1].open_time == candle.open_time:
            target[-1] = candle
        else:
            for index in range(len(target) - 1, -1, -1):
                if target[index].open_time == candle.open_time:
                    target[index] = candle
                    break
        await self.db.save_candle(candle)
        if candle.interval == "5m":
            await self.settle_market(candle)

    async def websocket_loop(self) -> None:
        streams = "/".join([
            f"{self.config.symbol.lower()}@aggTrade",
            f"{self.config.symbol.lower()}@kline_1m",
            f"{self.config.symbol.lower()}@kline_5m",
        ])
        url = f"{BINANCE_WS}?streams={streams}"
        retry = 1
        while not self.stop_event.is_set():
            try:
                if not self.http:
                    await asyncio.sleep(1)
                    continue
                async with self.http.ws_connect(url, heartbeat=15, autoping=True) as ws:
                    self.ws_connected = True
                    self.last_market_error = ""
                    retry = 1
                    log.info("Binance websocket connected")
                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = message.json()
                            data = payload.get("data", payload)
                            if isinstance(data, dict):
                                await self.handle_market_message(data)
                        elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            raise ConnectionError(f"websocket closed: {message.type}")
                    raise ConnectionError("websocket stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.ws_connected = False
                self.ws_reconnects += 1
                self.last_market_error = f"WS: {type(exc).__name__}: {exc}"
                log.warning("%s; reconnect in %ss", self.last_market_error, retry)
                await asyncio.sleep(retry)
                retry = min(retry * 2, 15)
            finally:
                self.ws_connected = False

    @staticmethod
    def _rest_candle(interval: str, row: list, now_ms: int) -> Candle:
        return Candle(
            interval, int(row[0]), int(row[6]), float(row[1]), float(row[2]), float(row[3]),
            float(row[4]), float(row[5]), int(row[6]) < now_ms,
        )

    async def rest_snapshot(self) -> None:
        if not self.http:
            return
        now_ms = self.server_now_ms()

        async def klines(interval: str):
            async with self.http.get(f"{BINANCE_REST}/fapi/v1/klines", params={"symbol": self.config.symbol, "interval": interval, "limit": 2}) as response:
                response.raise_for_status()
                return await response.json()

        async def ticker():
            async with self.http.get(f"{BINANCE_REST}/fapi/v1/ticker/price", params={"symbol": self.config.symbol}) as response:
                response.raise_for_status()
                return await response.json()

        m1_rows, m5_rows, price_row = await asyncio.gather(klines("1m"), klines("5m"), ticker())
        self.live_price = float(price_row["price"])
        for interval, rows in (("1m", m1_rows), ("5m", m5_rows)):
            for row in rows:
                candle = self._rest_candle(interval, row, now_ms)
                if candle.closed:
                    await self._store_closed(candle)
                else:
                    setattr(self, "live_m1" if interval == "1m" else "live_m5", candle)
                    if interval == "5m":
                        self.schedule_decision(candle, now_ms)
        self.last_rest_ok_mono = time.monotonic()
        self.rest_fallback_hits += 1

    async def rest_fallback_loop(self) -> None:
        while True:
            try:
                age = self._age(self.last_any_rx_mono)
                if age is None or age > WS_STALE_SECONDS:
                    try:
                        await self.rest_snapshot()
                    except Exception as exc:
                        self.last_market_error = f"REST: {type(exc).__name__}: {exc}"
                        log.warning("REST fallback failed: %s", exc)
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("REST fallback supervisor recovered an unexpected error")
                await asyncio.sleep(1)

    async def history_repair_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(60)
                await self.sync_server_time()
                if len(self.m1) < M1_24H - 5 or len(self.m5) < M5_24H - 2:
                    await self.backfill()
                await self.settle_pending()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("History repair: %s", exc)

    async def decision_watchdog_loop(self) -> None:
        """Decision creation does not depend on receiving the M5 kline stream."""
        while True:
            try:
                now_ms = self.server_now_ms()
                bucket = Candle.bucket_open_time("5m", now_ms)
                elapsed = (now_ms - bucket) / 1000.0
                if elapsed <= max(22, self.config.decision_second + 3):
                    if self.live_m5 is None or self.live_m5.open_time != bucket:
                        try:
                            await self.rest_snapshot()
                        except Exception:
                            pass
                    if self.live_m5 is not None and self.live_m5.open_time == bucket:
                        self.schedule_decision(self.live_m5, now_ms)
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Decision watchdog recovered an error")
                await asyncio.sleep(0.5)

    @staticmethod
    def decision_delay(open_time_ms: int, event_time_ms: int, decision_second: int) -> float | None:
        elapsed = max(0.0, (event_time_ms - open_time_ms) / 1000.0)
        if elapsed > max(22, decision_second + 3):
            return None
        return max(0.0, decision_second - elapsed)

    def schedule_decision(self, candle: Candle | None, event_time_ms: int) -> None:
        if candle is None or candle.open_time in self.decision_tasks:
            return
        delay = self.decision_delay(candle.open_time, event_time_ms, self.config.decision_second)
        if delay is None:
            return
        self.decision_tasks[candle.open_time] = asyncio.create_task(self.make_decision(candle.open_time, delay))

    async def _row_for_signal(self, open_time: int):
        return await (await self.db.conn.execute("SELECT * FROM signals WHERE market_open_time=?", (open_time,))).fetchone()

    @staticmethod
    def _prediction_from_row(row) -> Prediction:
        return Prediction(
            int(row["market_open_time"]), int(row["market_close_time"]), float(row["target_price"]),
            float(row["signal_price"]), row["direction"], float(row["confidence"]),
            float(row["m1_probability"]), float(row["m5_probability"]), int(row["pattern_samples"]),
            float(row["bet_amount"]), int(row["bet_step"]), bool(row["actual"]),
        )

    async def current_analysis_mode(self) -> str:
        return normalize_analysis_mode(await self.db.get("analysis_mode", "AUTO"))

    async def mode_stats_since_reset(self) -> dict[str, dict]:
        reset_at = int(await self.db.get("stats_reset_at", "0"))
        raw = await self.db.mode_stats(max(0, reset_at))
        empty = {"wins": 0, "losses": 0, "ties": 0, "decided": 0, "total": 0, "win_rate": 0.0}
        return {mode: dict(raw.get(mode, empty)) for mode in ANALYSIS_MODES}

    async def make_decision(self, open_time: int, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            live = self.live_m5
            if live is None or live.open_time != open_time:
                try:
                    await self.rest_snapshot()
                except Exception:
                    pass
                live = self.live_m5
            if live is None or live.open_time != open_time:
                self.last_decision_state = "LỖI: KHÔNG CÓ NẾN M5 LIVE"
                await self.db.event("DECISION_SKIPPED_NO_MARKET", {"open_time": open_time})
                return
            if self.live_price <= 0:
                self.live_price = live.close
            target = live.open

            # All nine modes analyze the exact same CLOSED M1/M5 candles every session.
            # Only the selected mode is promoted to the normal signal table/Telegram.
            predictions = all_mode_predictions(list(self.m1), list(self.m5), self.live_price, target)
            await self.db.create_mode_signals(open_time, live.close_time, target, predictions)

            mode = await self.current_analysis_mode()
            direction, confidence, p1, p5, samples = predictions[mode]
            actual = await self.signals_enabled()
            base_bet = float(await self.db.get("base_bet", str(self.config.base_bet)))
            step = int(await self.db.get("bet_step", "1"))
            bet = min(base_bet * (2 if step == 2 else 1), self.config.max_bet)
            prediction = Prediction(open_time, live.close_time, target, self.live_price, direction, confidence, p1, p5, samples, bet, step, actual)
            created = await self.db.create_signal(prediction)
            self.last_decision_open = open_time
            self.last_decision_state = "ĐÃ TẠO" if created else "ĐÃ TỒN TẠI"
            row = await self._row_for_signal(open_time)
            if row is not None and bool(row["actual"]) and row["telegram_message_id"] is None:
                try:
                    message_id = await self.telegram.send(await self.signal_text(self._prediction_from_row(row)), enabled=True)
                    await self.db.update_message_id(open_time, message_id)
                    self.last_decision_state = "ĐÃ GỬI TELEGRAM"
                except Exception as exc:
                    self.last_decision_state = "ĐÃ TẠO - CHỜ GỬI LẠI TELE"
                    await self.db.event("SIGNAL_SEND_ERROR", {"open_time": open_time, "error": str(exc)})
            await self.db.event("DECISION_CREATED", {
                "open_time": open_time,
                "direction": direction,
                "actual": actual,
                "confidence": confidence,
                "created": created,
                "analysis_mode": mode,
                "shadow_modes": len(predictions),
            })
        except Exception as exc:
            self.last_decision_state = f"LỖI: {type(exc).__name__}"
            log.exception("Decision failed for %s", open_time)
            try:
                await self.db.event("DECISION_ERROR", {"open_time": open_time, "error": str(exc)})
            except Exception:
                pass
        finally:
            self.decision_tasks.pop(open_time, None)

    async def retry_unsent_loop(self) -> None:
        while True:
            try:
                now_ms = self.server_now_ms()
                rows = await (await self.db.conn.execute(
                    """SELECT * FROM signals WHERE actual=1 AND telegram_message_id IS NULL
                       AND market_close_time>? ORDER BY market_open_time LIMIT 5""", (now_ms,)
                )).fetchall()
                for row in rows:
                    try:
                        message_id = await self.telegram.send(await self.signal_text(self._prediction_from_row(row)), enabled=True)
                        await self.db.update_message_id(int(row["market_open_time"]), message_id)
                    except Exception as exc:
                        self.telegram.last_error = str(exc)
                        break
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Telegram outbox loop recovered an error")
                await asyncio.sleep(5)

    async def signals_enabled(self) -> bool:
        if await self.db.get("manual_enabled", "1") != "1":
            return False
        pause_until = int(await self.db.get("risk_pause_until", "0"))
        now_ms = self.server_now_ms()
        if pause_until > now_ms:
            return False
        if pause_until:
            await self.db.set("risk_pause_until", 0)
            await self.db.set("risk_cycle_losses", 0)
            try:
                await self.telegram.send("✅ <b>ĐÃ HẾT 30 PHÚT TẠM NGHỈ</b>\nBot bắt đầu gửi tín hiệu mới.")
            except Exception:
                pass
        return True

    async def settle_market(self, candle: Candle) -> None:
        rows = [row for row in await self.db.pending() if int(row["market_open_time"]) == candle.open_time]
        for row in rows:
            await self.settle_row(row, candle.close)
        await self.db.settle_mode_signals(candle.open_time, candle.close)

    async def settle_pending(self) -> None:
        if not self.http:
            return
        now_ms = self.server_now_ms()
        for row in await self.db.pending():
            if int(row["market_close_time"]) >= now_ms:
                continue
            params = {"symbol": self.config.symbol, "interval": "5m", "startTime": int(row["market_open_time"]), "limit": 1}
            async with self.http.get(f"{BINANCE_REST}/fapi/v1/klines", params=params) as response:
                response.raise_for_status()
                data = await response.json()
            if data and int(data[0][0]) == int(row["market_open_time"]):
                await self.settle_row(row, float(data[0][4]))

        # Shadow mode results must also survive restart even if sending was paused.
        pending_modes = await self.db.pending_modes()
        mode_sessions: dict[int, int] = {}
        for row in pending_modes:
            mode_sessions[int(row["market_open_time"])] = int(row["market_close_time"])
        for open_time, close_time in sorted(mode_sessions.items()):
            if close_time >= now_ms:
                continue
            params = {"symbol": self.config.symbol, "interval": "5m", "startTime": open_time, "limit": 1}
            async with self.http.get(f"{BINANCE_REST}/fapi/v1/klines", params=params) as response:
                response.raise_for_status()
                data = await response.json()
            if data and int(data[0][0]) == open_time:
                await self.db.settle_mode_signals(open_time, float(data[0][4]))

    async def settle_row(self, row, close_price: float) -> None:
        target = float(row["target_price"])
        direction = row["direction"]
        if close_price == target:
            result = "TIE"
        else:
            result = "WIN" if (direction == "UP") == (close_price > target) else "LOSS"
        payout = float(await self.db.get("payout_rate", str(self.config.payout_rate)))
        bet = float(row["bet_amount"])
        pnl = bet * payout if result == "WIN" else (-bet if result == "LOSS" else 0.0)
        await self.db.settle(int(row["market_open_time"]), result, close_price, pnl if row["actual"] else 0.0)
        if row["actual"]:
            await self.apply_money_management(row, result, pnl)
            try:
                await self.telegram.send(await self.result_text(row, close_price, result, pnl), keyboard=False)
            except Exception as exc:
                await self.db.event("RESULT_SEND_ERROR", {"open_time": int(row["market_open_time"]), "error": str(exc)})

    async def apply_money_management(self, row, result: str, pnl: float) -> None:
        balance = float(await self.db.get("current_balance", "0")) + pnl
        await self.db.set("current_balance", f"{balance:.8f}")
        step = int(row["bet_step"])
        await self.db.set("bet_step", 2 if step == 1 and result == "WIN" else 1)
        cycle_losses = int(await self.db.get("risk_cycle_losses", "0"))
        cycle_losses = 0 if result == "WIN" else cycle_losses + (1 if result == "LOSS" else 0)
        await self.db.set("risk_cycle_losses", cycle_losses)
        if cycle_losses >= 2:
            until = self.server_now_ms() + 30 * 60 * 1000
            await self.db.set("risk_pause_until", until)
            await self.db.set("pause_started_at", self.server_now_ms())

    def day_start_ms(self) -> int:
        now = datetime.now(self.config.timezone)
        start = datetime.combine(now.date(), dt_time.min, tzinfo=self.config.timezone)
        return int(start.timestamp() * 1000)

    @staticmethod
    def _bucket_line(icon: str, label: str, stats: dict) -> str:
        decided = int(stats.get("decided", 0))
        wins = int(stats.get("wins", 0))
        losses = int(stats.get("losses", 0))
        ties = int(stats.get("ties", 0))
        if decided <= 0:
            value = "chưa có dữ liệu"
        else:
            value = f"<b>{stats.get('win_rate', 0.0):.1f}%</b> ({wins} thắng/{losses} thua)"
        if ties:
            value += f" + {ties} hòa"
        return f"{icon} {label}: {value}"

    async def threshold_stats_text(self) -> str:
        reset_at = int(await self.db.get("stats_reset_at", "0"))
        buckets = await self.db.confidence_stats(max(0, reset_at), actual_only=False)
        return (
            "📈 <b>TỶ LỆ THẮNG THEO NGƯỠNG TIN CẬY</b>\n"
            + self._bucket_line("🔴", "THẤP 50.0–56.9%", buckets["LOW"]) + "\n"
            + self._bucket_line("🟡", "TRUNG BÌNH 57.0–64.9%", buckets["MEDIUM"]) + "\n"
            + self._bucket_line("🟢", "CAO ≥65.0%", buckets["HIGH"]) + "\n"
            "<i>Tính trên các phiên đã chấm từ lần reset; hòa không tính vào mẫu thắng/thua.</i>"
        )

    async def stats_text(self) -> str:
        reset_at = int(await self.db.get("stats_reset_at", "0"))
        persistent_start = max(0, reset_at)
        today_start = max(self.day_start_ms(), persistent_start)
        actual = await self.db.stats(persistent_start, actual_only=True)
        virtual = await self.db.stats(persistent_start, actual_only=False)
        today = await self.db.stats(today_start, actual_only=True)
        balance = float(await self.db.get("current_balance", "0"))
        actual_total = (actual["wins"] or 0) + (actual["losses"] or 0) + (actual["ties"] or 0)
        virtual_decided = (virtual["wins"] or 0) + (virtual["losses"] or 0)
        win_rate = ((virtual["wins"] or 0) / virtual_decided * 100) if virtual_decided else 0
        return (
            "\n\n📊 <b>THỐNG KÊ TỪ LẦN RESET</b>\n"
            f"🟢 Thắng: <b>{actual['wins'] or 0}</b> | 🔴 Thua: <b>{actual['losses'] or 0}</b> | ➖ Hòa: <b>{actual['ties'] or 0}</b>\n"
            f"📋 Tổng lệnh thực tế: <b>{actual_total}</b>\n"
            f"💰 Tổng tiền đã đặt: <b>{actual['staked']:.2f} USDT</b>\n"
            f"💵 Lãi/lỗ ròng: <b>{actual['pnl']:+.2f} USDT</b>\n"
            f"💳 Số dư hiện tại: <b>{balance:.2f} USDT</b>\n"
            f"📅 Hôm nay: {today['wins'] or 0} thắng | {today['losses'] or 0} thua | {today['ties'] or 0} hòa\n\n"
            f"📡 <b>PHÂN TÍCH TỪ LẦN RESET</b>\n"
            f"Thắng: {virtual['wins'] or 0} | Thua: {virtual['losses'] or 0} | Hòa: {virtual['ties'] or 0}\n"
            f"Tỷ lệ thắng: {win_rate:.1f}%\n\n"
            + await self.threshold_stats_text()
        )

    async def signal_text(self, p: Prediction) -> str:
        local_open = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp(p.market_close_time / 1000, self.config.timezone)
        label = "🟢 𝗠𝗨𝗔 𝗧Ă𝗡𝗚" if p.direction == "UP" else "🔴 𝗠𝗨𝗔 𝗚𝗜Ả𝗠"
        m1_analysis = candle_analysis(list(self.m1), "M1")
        m5_analysis = candle_analysis(list(self.m5), "M5")
        mode = await self.current_analysis_mode()
        return (
            f"📥 <b>TIN NHẮN VÀO LỆNH • V{APP_VERSION}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{label}: {p.bet_amount:.2f} USDT</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ Phiên: {local_open:%H:%M}–{local_close:%H:%M}\n"
            f"🎯 Target: <code>{p.target_price:,.2f}</code> USDT\n"
            f"💵 Giá lúc báo: <code>{p.signal_price:,.2f}</code> USDT\n"
            f"🧠 Chế độ gửi lệnh: <b>{analysis_mode_label(mode)}</b>\n"
            f"\n{self.confidence_block(p.confidence)}\n\n"
            f"🔎 M1: {p.m1_probability * 100:.1f}% tăng | M5: {p.m5_probability * 100:.1f}% tăng\n"
            f"🕯 {m1_analysis}\n🕯 {m5_analysis}\n"
            f"🧩 Mẫu 5 nến: <b>{p.confidence * 100:.1f}%</b> ({p.pattern_samples} mẫu)\n"
            f"🔢 Tầng tiền: <b>LỆNH {p.bet_step}</b>" + await self.stats_text()
        )

    async def result_text(self, row, close_price: float, result: str, pnl: float) -> str:
        direction = "TĂNG" if row["direction"] == "UP" else "GIẢM"
        return {
            "WIN": f"✅ <b>ĐÃ THẮNG {direction}</b>",
            "LOSS": f"❌ <b>ĐÃ THUA {direction}</b>",
            "TIE": f"➖ <b>ĐÃ HÒA {direction}</b>",
        }[result]

    @staticmethod
    def confidence_block(confidence: float) -> str:
        if confidence >= 0.65:
            icon, quality = "🟢", "CAO"
        elif confidence >= 0.57:
            icon, quality = "🟡", "TRUNG BÌNH"
        else:
            icon, quality = "🔴", "THẤP"
        return f"━━━━━━━━━━━━━━━━━━━━\n{icon} <b>ĐỘ TIN CẬY: {quality} – {confidence * 100:.1f}%</b>\n━━━━━━━━━━━━━━━━━━━━"

    async def status_text(self) -> str:
        manual = await self.db.get("manual_enabled", "1") == "1"
        pause_until = int(await self.db.get("risk_pause_until", "0"))
        now_ms = self.server_now_ms()
        paused = pause_until > now_ms
        base = float(await self.db.get("base_bet", str(self.config.base_bet)))
        step = int(await self.db.get("bet_step", "1"))
        mode = await self.current_analysis_mode()
        trade_age = self._age(self.last_trade_rx_mono)
        kline_age = self._age(self.last_kline_rx_mono)
        rest_age = self._age(self.last_rest_ok_mono)
        if trade_age is not None and trade_age <= WS_STALE_SECONDS:
            source = "🟢 WEBSOCKET TICK"
        elif rest_age is not None and rest_age <= REST_STALE_SECONDS:
            source = "🟡 REST DỰ PHÒNG"
        else:
            source = "🔴 MẤT DỮ LIỆU"
        if paused:
            pause_local = datetime.fromtimestamp(pause_until / 1000, self.config.timezone).strftime("%H:%M:%S")
            send_state = f"TẠM NGHỈ RỦI RO TỚI {pause_local}"
        else:
            send_state = "ĐANG CHẠY" if manual else "ĐANG DỪNG THỦ CÔNG"
        telegram_state = "⚠️ XUNG ĐỘT POLLING" if self.telegram.poll_conflict else ("OK" if not self.telegram.last_error else "CÓ LỖI")
        error_line = self.last_market_error[-180:] if self.last_market_error else "không"
        trade_age_value = trade_age if trade_age is not None else -1.0
        kline_age_value = kline_age if kline_age is not None else -1.0
        return (
            f"🤖 <b>BÁO CÁO BOT V{APP_VERSION}</b>\n"
            f"🧠 Chế độ gửi lệnh: <b>{analysis_mode_label(mode)}</b>\n"
            f"🧪 So sánh nền: <b>{len(ANALYSIS_MODES)} chế độ / mỗi phiên 5 phút</b>\n"
            f"Nguồn giá: <b>{source}</b>\n"
            f"WebSocket: <b>{'CONNECTED' if self.ws_connected else 'RECONNECTING'}</b> | reconnect: {self.ws_reconnects}\n"
            f"Tick aggTrade: <b>{self.trade_ticks:,}</b> | tuổi tick: <b>{trade_age_value:.2f}s</b>\n"
            f"Kline age: <b>{kline_age_value:.2f}s</b> | REST fallback: <b>{self.rest_fallback_hits}</b>\n"
            f"Giá BTC: <code>{self.live_price:,.2f}</code> USDT\n"
            f"M1/M5 lịch sử: <b>{len(self.m1)}/{len(self.m5)}</b>\n"
            f"Tạo lệnh: <b>{self.last_decision_state}</b>\n"
            f"Gửi lệnh: <b>{send_state}</b>\n"
            f"Telegram: <b>{telegram_state}</b>\n"
            f"Lỗi thị trường gần nhất: <code>{error_line}</code>\n"
            f"DB: <code>{self.database_path}</code>\n"
            f"Vốn gốc: <b>{base:.2f}</b> | Tầng: <b>LỆNH {step}</b>" + await self.stats_text()
        )

    async def _set_analysis_mode(self, mode: str) -> str:
        selected = normalize_analysis_mode(mode)
        await self.db.set("analysis_mode", selected)
        await self.db.event("ANALYSIS_MODE_CHANGED", {"mode": selected})
        return selected

    async def handle_telegram(self, kind: str, value: str, raw: dict) -> None:
        if kind == "callback":
            if value == "stop":
                await self.db.set("manual_enabled", 0)
                await self.db.set("pause_started_at", self.server_now_ms())
                await self.telegram.send("🔴 <b>ĐÃ DỪNG GỬI LỆNH</b>\nPhân tích 9 chế độ vẫn tiếp tục ở nền.", enabled=False)
            elif value == "start":
                await self.db.set("manual_enabled", 1)
                await self.db.set("risk_pause_until", 0)
                await self.db.set("risk_cycle_losses", 0)
                await self.telegram.send("🟢 <b>BOT ĐANG CHẠY</b>" + await self.stats_text(), enabled=True)
            elif value == "status":
                await self.telegram.send(await self.status_text(), enabled=await self.db.get("manual_enabled", "1") == "1")
            elif value == "analysis_mode":
                await self.telegram.send_analysis_mode_menu(
                    await self.current_analysis_mode(),
                    await self.mode_stats_since_reset(),
                )
            elif value.startswith("mode_"):
                selected = await self._set_analysis_mode(value[5:])
                await self.telegram.send(
                    f"🧠 Đã chọn chế độ gửi lệnh: <b>{analysis_mode_label(selected)}</b>\n"
                    "Từ phiên 5 phút kế tiếp chỉ lệnh của chế độ này được gửi về Telegram. "
                    "8 chế độ còn lại vẫn phân tích và tự chấm thắng/thua ở nền."
                )
            elif value == "threshold_stats":
                await self.telegram.send(await self.threshold_stats_text())
            elif value == "setbet_help":
                await self.db.set("awaiting_setbet", 1)
                await self.telegram.ask("💵 <b>NHẬP VỐN LỆNH 1</b>\nVí dụ nhập <code>2</code> → Lệnh 1 = 2 USDT, Lệnh 2 = 4 USDT.", "Ví dụ: 2")
            elif value == "reset_stats":
                await self.telegram.ask_reset_confirmation()
            elif value == "reset_cancel":
                await self.telegram.send("❎ Đã hủy reset thống kê.")
            elif value == "reset_confirm":
                now_ms = self.server_now_ms()
                await self.db.set("stats_reset_at", now_ms)
                await self.db.set("current_balance", 0)
                await self.db.set("bet_step", 1)
                await self.db.set("risk_cycle_losses", 0)
                await self.db.set("risk_pause_until", 0)
                await self.db.event("STATS_RESET", {"reset_at": now_ms})
                await self.telegram.send("♻️ <b>ĐÃ RESET THỐNG KÊ VỀ 0</b>")
            return

        parts = value.split()
        command = parts[0].lower() if parts else ""
        try:
            awaiting = await self.db.get("awaiting_setbet", "0") == "1"
            if awaiting and command not in ("/cancel", "/status", "/start"):
                amount = float(value.replace(",", "."))
                if amount <= 0 or amount * 2 > self.config.max_bet:
                    raise ValueError
                await self.db.set("base_bet", amount)
                await self.db.set("awaiting_setbet", 0)
                await self.telegram.send(f"✅ Vốn Lệnh 1: <b>{amount:.2f} USDT</b> | Lệnh 2: <b>{amount * 2:.2f} USDT</b>")
            elif command == "/cancel":
                await self.db.set("awaiting_setbet", 0)
                await self.telegram.send("Đã hủy nhập vốn.")
            elif command == "/setbet" and len(parts) == 2:
                amount = float(parts[1])
                if amount <= 0 or amount * 2 > self.config.max_bet:
                    raise ValueError
                await self.db.set("base_bet", amount)
                await self.db.set("awaiting_setbet", 0)
                await self.telegram.send(f"✅ Vốn Lệnh 1: <b>{amount:.2f}</b> | Lệnh 2: <b>{amount * 2:.2f}</b>")
            elif command == "/setbalance" and len(parts) == 2:
                amount = float(parts[1])
                await self.db.set("current_balance", amount)
                await self.telegram.send(f"✅ Số dư: <b>{amount:.2f} USDT</b>")
            elif command == "/setpayout" and len(parts) == 2:
                rate = float(parts[1])
                rate = rate / 100 if rate > 2 else rate
                if not 0 < rate <= 2:
                    raise ValueError
                await self.db.set("payout_rate", rate)
                await self.telegram.send(f"✅ Tỷ lệ trả thưởng: <b>{rate * 100:.1f}%</b>")
            elif command in ("/mode", "/modes"):
                if len(parts) == 1:
                    await self.telegram.send_analysis_mode_menu(
                        await self.current_analysis_mode(),
                        await self.mode_stats_since_reset(),
                    )
                elif len(parts) == 2:
                    requested = parts[1].upper()
                    aliases = {
                        "BALANCE": "AUTO", "AUTO": "AUTO",
                        "M1": "M1", "M5": "M5", "AGREE": "AGREE",
                        "MOMENTUM": "MOMENTUM", "STRUCTURE": "STRUCTURE",
                        "WICK": "WICK", "PATTERN": "PATTERN", "BREAKOUT": "BREAKOUT",
                    }
                    if requested not in aliases:
                        raise ValueError
                    selected = await self._set_analysis_mode(aliases[requested])
                    await self.telegram.send(f"🧠 Chế độ gửi lệnh: <b>{analysis_mode_label(selected)}</b>")
                else:
                    raise ValueError
            elif command == "/thresholds":
                await self.telegram.send(await self.threshold_stats_text())
            elif command in ("/status", "/start"):
                await self.telegram.send(await self.status_text())
            else:
                await self.telegram.send(
                    "Lệnh: /status, /mode, /modes, /thresholds, /setbet 1, /setbalance 100, /setpayout 80"
                )
        except (ValueError, IndexError):
            await self.telegram.send(
                "⚠️ Giá trị không hợp lệ. Ví dụ: <code>/setbet 1</code> hoặc <code>/mode MOMENTUM</code>"
            )

    async def safe_startup_message(self) -> None:
        try:
            enabled = await self.db.get("manual_enabled", "1") == "1"
            mode = await self.current_analysis_mode()
            await self.telegram.send(
                f"🤖 <b>BOT V{APP_VERSION} ĐÃ KHỞI ĐỘNG</b>\n"
                f"🧠 Chế độ gửi lệnh: <b>{analysis_mode_label(mode)}</b>\n"
                f"🧪 {len(ANALYSIS_MODES)} chế độ vẫn phân tích song song mỗi phiên 5 phút.\n"
                "WebSocket + REST dự phòng + watchdog tạo lệnh đã bật.",
                enabled=enabled,
            )
        except Exception as exc:
            self.telegram.last_error = str(exc)
            log.warning("Startup Telegram send failed; market engine continues: %s", exc)

    async def run(self) -> None:
        await self.setup()
        await self.safe_startup_message()
        tasks = [
            asyncio.create_task(self.websocket_loop(), name="binance-ws"),
            asyncio.create_task(self.rest_fallback_loop(), name="rest-fallback"),
            asyncio.create_task(self.decision_watchdog_loop(), name="decision-watchdog"),
            asyncio.create_task(self.history_repair_loop(), name="history-repair"),
            asyncio.create_task(self.retry_unsent_loop(), name="telegram-outbox"),
            asyncio.create_task(self.telegram.poll(), name="telegram-poll"),
        ]
        await self.stop_event.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.close()


async def async_main() -> None:
    config = Config()
    config.validate()
    logging.basicConfig(level=getattr(logging, config.log_level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bot = TradingSignalBotV3(config)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bot.stop_event.set)
        except NotImplementedError:
            pass
    await bot.run()


if __name__ == "__main__":
    asyncio.run(async_main())
