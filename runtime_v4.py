from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import aiohttp
import aiosqlite

from config import Config
from prediction_source import PredictionHistorySource

APP_VERSION = "4.1.0"
BINANCE_REST = "https://fapi.binance.com"
INTERVAL_MS = 300_000
POLL_SECONDS = 1.0
FRESH_SIGNAL_GRACE_MS = 45_000

RED = "R"
GREEN = "G"
COLOR_LABEL = {RED: "ĐỎ", GREEN: "XANH"}
COLOR_ICON = {RED: "🔴", GREEN: "🟢"}

# Exact 5-candle recognition table from the operator's reference image.
# Key = five most recent closed candles; value = buy color for the next M5 candle.
FIVE_CANDLE_PATTERNS: dict[str, str] = {
    "RGGRR": RED,
    "GRRGR": RED,
    "GGRRR": GREEN,
    "RRGGR": GREEN,
    "RGGRG": GREEN,
    "GRRGG": GREEN,
    "GGRRG": RED,
    "RRGGG": RED,
    "RGGGR": GREEN,
    "RRRGR": RED,
    "GGGRR": GREEN,
    "GRRRR": RED,
    "RGRRR": GREEN,
    "GRGGR": RED,
    "RRGRR": RED,
    "GGRGR": GREEN,
    "RGGGG": GREEN,
    "RRRGG": RED,
    "GGGRG": GREEN,
    "GRRRG": RED,
    "RGRRG": GREEN,
    "GRGGG": RED,
    "RRGRG": RED,
    "GGRGG": GREEN,
}

log = logging.getLogger("boss-vao-lenh-v4")


def candle_color(open_price: float, close_price: float) -> str | None:
    if close_price > open_price:
        return GREEN
    if close_price < open_price:
        return RED
    return None


def recognize_five_candle_pattern(colors: Iterable[str | None]) -> str | None:
    values = tuple(colors)
    if len(values) != 5 or any(value not in (RED, GREEN) for value in values):
        return None
    return FIVE_CANDLE_PATTERNS.get("".join(value for value in values if value is not None))


def next_bet_step(previous_step: int, result: str) -> int:
    """Lệnh 1 thắng -> Lệnh 2; sau Lệnh 2 hoặc Lệnh 1 thua -> về Lệnh 1."""
    if int(previous_step) == 1 and result == "WIN":
        return 2
    return 1


def result_for_direction(direction: str, actual_color: str | None) -> str:
    if actual_color not in (RED, GREEN):
        return "VOID"
    return "WIN" if direction == actual_color else "LOSS"


def _money(value: float) -> str:
    return f"{float(value):,.2f}"


@dataclass(slots=True)
class ClosedCandle:
    open_time: int
    close_time: int
    open: float
    close: float
    resolved_color: str | None = None

    @classmethod
    def from_binance(cls, row: list[Any]) -> "ClosedCandle":
        return cls(
            open_time=int(row[0]),
            close_time=int(row[6]),
            open=float(row[1]),
            close=float(row[4]),
        )

    @property
    def color(self) -> str | None:
        return self.resolved_color or candle_color(self.open, self.close)


class TelegramSignalSender:
    """One-way Telegram sender. V4 does not poll commands or send result/status cards."""

    def __init__(self, token: str, chat_id: str):
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.session: aiohttp.ClientSession | None = None
        self.last_error = ""

    async def open(self) -> None:
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def send(self, text: str) -> int:
        if not self.session:
            raise RuntimeError("Telegram session chưa mở")
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with self.session.post(f"{self.base_url}/sendMessage", json=payload) as response:
            data = await response.json(content_type=None)
            if not response.ok or not data.get("ok"):
                raise RuntimeError(str(data.get("description", data)))
            self.last_error = ""
            return int(data["result"]["message_id"])


class PatternSignalBot:
    """Boss V4: only the fixed 5-candle recognition table is active."""

    def __init__(self, config: Config):
        self.config = config
        self.db: aiosqlite.Connection | None = None
        self.http: aiohttp.ClientSession | None = None
        self.telegram = TelegramSignalSender(config.telegram_token, config.telegram_chat_id)
        self.prediction_history: PredictionHistorySource | None = None
        self.mobile_server = None
        self.stop_event = asyncio.Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._state_lock = threading.RLock()
        self._settings_lock = asyncio.Lock()
        self._snapshot: dict[str, Any] = {
            "version": APP_VERSION,
            "connected": False,
            "status": "Đang khởi động...",
            "error": "",
            "symbol": config.symbol,
            "source_label": "Binance Prediction BTC Up/Down 5m" if config.prediction_source == "predictfun" else "Binance Futures M5",
            "source_error": "",
            "telegram_status": "Chưa gửi / chưa kiểm tra",
            "mobile_status": "Chưa khởi động",
            "mobile_port": int(config.mobile_port),
            "colors": [],
            "pattern": "-----",
            "recommendation": None,
            "frame": "--:--–--:--",
            "current_step": 1,
            "next_bet": float(config.base_bet),
            "bet1": float(config.base_bet),
            "bet2": float(getattr(config, "second_bet", config.base_bet * 2.0)),
            "payout_percent": float(config.payout_rate) * 100.0,
            "telegram_enabled": True,
            "day": "",
            "start_balance": float(getattr(config, "start_balance", 0.0)),
            "daily_pnl": 0.0,
            "end_balance": float(getattr(config, "start_balance", 0.0)),
            "wins": 0,
            "losses": 0,
            "history": [],
            "history_details": [],
            "previous_day": None,
            "last_signal": None,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            data = dict(self._snapshot)
            data["colors"] = list(self._snapshot.get("colors", []))
            data["history"] = list(self._snapshot.get("history", []))
            data["history_details"] = [dict(x) for x in self._snapshot.get("history_details", [])]
            previous = self._snapshot.get("previous_day")
            data["previous_day"] = dict(previous) if isinstance(previous, dict) else previous
            last_signal = self._snapshot.get("last_signal")
            data["last_signal"] = dict(last_signal) if isinstance(last_signal, dict) else last_signal
            return data

    def _set_snapshot(self, **updates: Any) -> None:
        with self._state_lock:
            self._snapshot.update(updates)

    @property
    def timezone(self):
        return self.config.timezone

    def _local_day(self, timestamp_ms: int | None = None) -> str:
        if timestamp_ms is None:
            return datetime.now(self.timezone).date().isoformat()
        return datetime.fromtimestamp(timestamp_ms / 1000, self.timezone).date().isoformat()

    async def _db_get(self, key: str, default: str) -> str:
        assert self.db is not None
        cursor = await self.db.execute("SELECT value FROM pattern_settings WHERE key=?", (key,))
        row = await cursor.fetchone()
        return str(row[0]) if row else default

    async def _db_set(self, key: str, value: Any) -> None:
        assert self.db is not None
        await self.db.execute(
            "INSERT INTO pattern_settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    async def _open_database(self) -> None:
        path = Path(self.config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA synchronous=NORMAL")
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS pattern_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pattern_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_open_time INTEGER NOT NULL UNIQUE,
                target_open_time INTEGER NOT NULL,
                pattern TEXT NOT NULL,
                direction TEXT NOT NULL,
                bet_step INTEGER NOT NULL,
                bet_amount REAL NOT NULL,
                created_at INTEGER NOT NULL,
                result TEXT,
                actual_color TEXT,
                settled_at INTEGER,
                pnl REAL NOT NULL DEFAULT 0,
                result_notified INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_pattern_signals_target
                ON pattern_signals(target_open_time);
            CREATE INDEX IF NOT EXISTS idx_pattern_signals_result
                ON pattern_signals(result, target_open_time DESC);

            CREATE TABLE IF NOT EXISTS pattern_daily (
                day TEXT PRIMARY KEY,
                start_balance REAL NOT NULL DEFAULT 0,
                pnl REAL NOT NULL DEFAULT 0,
                end_balance REAL NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                voids INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL
            );
            """
        )
        cursor = await self.db.execute("PRAGMA table_info(pattern_signals)")
        columns = {str(row["name"]) for row in await cursor.fetchall()}
        if "result_notified" not in columns:
            await self.db.execute(
                "ALTER TABLE pattern_signals ADD COLUMN result_notified INTEGER NOT NULL DEFAULT 0"
            )
            # Existing settled V4 rows predate result Telegram messages. Do not replay
            # an old backlog after upgrading; only new settlements are announced.
            await self.db.execute(
                "UPDATE pattern_signals SET result_notified=1 WHERE result IS NOT NULL"
            )

        default_bet1 = float(self.config.base_bet)
        default_bet2 = float(getattr(self.config, "second_bet", default_bet1 * 2.0))
        default_start = float(getattr(self.config, "start_balance", 0.0))
        defaults = {
            "bet1": default_bet1,
            "bet2": default_bet2,
            "payout_rate": float(self.config.payout_rate),
            "telegram_enabled": 1,
            "current_step": 1,
            "default_start_balance": default_start,
            "last_source_open_time": 0,
        }
        for key, value in defaults.items():
            await self.db.execute(
                "INSERT OR IGNORE INTO pattern_settings(key,value) VALUES(?,?)",
                (key, str(value)),
            )
        previous_source = await self._db_get("market_data_source", "")
        current_source = self.config.prediction_source
        if previous_source != current_source:
            # V4.0 used Futures candle colors. Those results are not comparable
            # with Binance Prediction/Predict.fun resolutions, so start clean when
            # switching sources instead of mixing two different color histories.
            await self.db.execute("DELETE FROM pattern_signals")
            await self.db.execute("DELETE FROM pattern_daily")
            await self._db_set("current_step", 1)
            await self._db_set("last_source_open_time", 0)
            await self._db_set("market_data_source", current_source)
        await self.db.commit()
        await self._ensure_day(self._local_day())

    async def _ensure_day(self, day: str) -> None:
        assert self.db is not None
        cursor = await self.db.execute("SELECT day FROM pattern_daily WHERE day=?", (day,))
        existing = await cursor.fetchone()
        if existing:
            return
        cursor = await self.db.execute(
            "SELECT end_balance FROM pattern_daily WHERE day < ? ORDER BY day DESC LIMIT 1", (day,)
        )
        previous = await cursor.fetchone()
        if previous:
            start = float(previous[0])
        else:
            start = float(await self._db_get("default_start_balance", "0"))
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        await self.db.execute(
            "INSERT OR IGNORE INTO pattern_daily(day,start_balance,pnl,end_balance,wins,losses,voids,updated_at) "
            "VALUES(?,?,?,?,0,0,0,?)",
            (day, start, 0.0, start, now_ms),
        )
        await self.db.commit()

    async def setup(self) -> None:
        self.loop = asyncio.get_running_loop()
        await self._open_database()
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        if self.config.prediction_source == "predictfun":
            self.prediction_history = PredictionHistorySource(
                self.http,
                self.config.predict_api_base,
                self.config.predict_api_key,
            )
        await self.telegram.open()
        await self._initial_market_sync()
        await self._refresh_snapshot()

    async def close(self) -> None:
        await self.telegram.close()
        if self.http and not self.http.closed:
            await self.http.close()
        if self.db:
            await self.db.close()

    async def _fetch_closed(self, limit: int = 30) -> list[ClosedCandle]:
        if not self.http:
            raise RuntimeError("HTTP session chưa mở")

        if self.config.prediction_source == "predictfun":
            if self.prediction_history is None:
                raise RuntimeError("Prediction source chưa khởi tạo")
            rounds = await self.prediction_history.recent(limit)
            if len(rounds) < 5:
                detail = self.prediction_history.last_error or "chưa đủ 5 vòng đã phân xử"
                self._set_snapshot(source_error=detail)
                raise RuntimeError(f"Không lấy đủ lịch sử Binance Prediction: {detail}")
            self._set_snapshot(source_error=self.prediction_history.last_error)
            return [
                ClosedCandle(
                    open_time=item.open_time,
                    close_time=item.close_time,
                    open=0.0,
                    close=0.0,
                    resolved_color=item.color,
                )
                for item in rounds
            ]

        params = {"symbol": self.config.symbol, "interval": "5m", "limit": max(6, min(200, limit))}
        async with self.http.get(f"{BINANCE_REST}/fapi/v1/klines", params=params) as response:
            response.raise_for_status()
            rows = await response.json()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return [ClosedCandle.from_binance(row) for row in rows if int(row[6]) < now_ms]

    async def _initial_market_sync(self) -> None:
        candles = await self._fetch_closed(40)
        if len(candles) < 5:
            raise RuntimeError("Không lấy đủ 5 kết quả 5 phút đã chốt")
        await self._settle_pending_from(candles)
        latest = candles[-1]
        stored = int(await self._db_get("last_source_open_time", "0"))
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if stored <= 0:
            if now_ms - latest.close_time <= FRESH_SIGNAL_GRACE_MS:
                await self._process_closed_candle(latest, candles, allow_signal=True)
            else:
                await self._db_set("last_source_open_time", latest.open_time)
                assert self.db is not None
                await self.db.commit()
        elif latest.open_time > stored:
            for candle in candles:
                if candle.open_time <= stored:
                    continue
                is_latest = candle.open_time == latest.open_time
                allow_signal = is_latest and now_ms - candle.close_time <= FRESH_SIGNAL_GRACE_MS
                await self._process_closed_candle(candle, candles, allow_signal=allow_signal)
        self._update_market_preview(candles[-5:])
        status = (
            "Đang theo dõi Binance Prediction BTC Up/Down 5m"
            if self.config.prediction_source == "predictfun"
            else "Đang theo dõi nến M5 Binance Futures"
        )
        self._set_snapshot(connected=True, status=status, error="")

    def _window_ending_at(self, candle: ClosedCandle, candles: list[ClosedCandle]) -> list[ClosedCandle]:
        index = next((i for i, item in enumerate(candles) if item.open_time == candle.open_time), -1)
        if index < 4:
            return []
        window = candles[index - 4:index + 1]
        if any(
            window[i].open_time - window[i - 1].open_time != INTERVAL_MS
            for i in range(1, len(window))
        ):
            return []
        return window

    def _update_market_preview(self, candles: list[ClosedCandle]) -> None:
        colors = [c.color for c in candles[-5:]]
        recommendation = recognize_five_candle_pattern(colors)
        if candles:
            next_open = candles[-1].open_time + INTERVAL_MS
            next_close = next_open + INTERVAL_MS
            frame = self._frame_text(next_open, next_close)
        else:
            frame = "--:--–--:--"
        self._set_snapshot(
            colors=colors,
            pattern="".join(value or "D" for value in colors),
            recommendation=recommendation,
            frame=frame,
        )

    def _frame_text(self, open_time: int, close_time_exclusive: int) -> str:
        start = datetime.fromtimestamp(open_time / 1000, self.timezone)
        end = datetime.fromtimestamp(close_time_exclusive / 1000, self.timezone)
        return f"{start:%H:%M}–{end:%H:%M}"

    async def _day_stats(self, day: str) -> dict[str, float | int]:
        assert self.db is not None
        await self._ensure_day(day)
        cursor = await self.db.execute(
            "SELECT start_balance,pnl,end_balance,wins,losses,voids FROM pattern_daily WHERE day=?",
            (day,),
        )
        row = await cursor.fetchone()
        return {
            "start_balance": float(row["start_balance"]),
            "pnl": float(row["pnl"]),
            "end_balance": float(row["end_balance"]),
            "wins": int(row["wins"]),
            "losses": int(row["losses"]),
            "voids": int(row["voids"]),
        }

    async def _settle_pending_from(self, candles: list[ClosedCandle]) -> None:
        for candle in candles:
            await self._settle_for_candle(candle)

    async def _settle_for_candle(self, candle: ClosedCandle) -> bool:
        """Settle first, send the result card, then allow the next entry card."""
        assert self.db is not None
        cursor = await self.db.execute(
            "SELECT * FROM pattern_signals WHERE target_open_time=? ORDER BY id DESC LIMIT 1",
            (candle.open_time,),
        )
        row = await cursor.fetchone()
        if row is None:
            return True

        result = str(row["result"] or "")
        actual = str(row["actual_color"] or "") or candle.color
        pnl = float(row["pnl"] or 0.0)
        settled_at = int(row["settled_at"] or candle.close_time)

        if not result:
            actual = candle.color
            result = result_for_direction(str(row["direction"]), actual)
            payout_rate = float(await self._db_get("payout_rate", str(self.config.payout_rate)))
            bet = float(row["bet_amount"])
            pnl = bet * payout_rate if result == "WIN" else (-bet if result == "LOSS" else 0.0)
            settled_at = candle.close_time
            await self.db.execute(
                "UPDATE pattern_signals "
                "SET result=?,actual_color=?,settled_at=?,pnl=?,result_notified=0 WHERE id=?",
                (result, actual, settled_at, pnl, int(row["id"])),
            )
            next_step = next_bet_step(int(row["bet_step"]), result)
            await self._db_set("current_step", next_step)

            day = self._local_day(candle.close_time)
            await self._ensure_day(day)
            win_inc = 1 if result == "WIN" else 0
            loss_inc = 1 if result == "LOSS" else 0
            void_inc = 1 if result == "VOID" else 0
            await self.db.execute(
                "UPDATE pattern_daily SET pnl=pnl+?, end_balance=start_balance+pnl+?, "
                "wins=wins+?, losses=losses+?, voids=voids+?, updated_at=? WHERE day=?",
                (pnl, pnl, win_inc, loss_inc, void_inc, settled_at, day),
            )
            await self.db.commit()
            log.info("Settled %s as %s actual=%s pnl=%.2f", row["pattern"], result, actual, pnl)
        else:
            day = self._local_day(settled_at)

        notified = int(row["result_notified"] or 0) == 1
        if notified:
            return True

        telegram_enabled = await self._db_get("telegram_enabled", "1") == "1"
        if not telegram_enabled:
            await self.db.execute(
                "UPDATE pattern_signals SET result_notified=1 WHERE id=?",
                (int(row["id"]),),
            )
            await self.db.commit()
            return True

        stats = await self._day_stats(day)
        settled = {
            "direction": str(row["direction"]),
            "bet_step": int(row["bet_step"]),
            "bet_amount": float(row["bet_amount"]),
            "target_open_time": int(row["target_open_time"]),
            "target_close_time": int(row["target_open_time"]) + INTERVAL_MS,
        }
        try:
            # This await is deliberate: the next M5 entry is not sent until the
            # WIN/LOSS message for the candle that just closed has been delivered.
            await self.telegram.send(
                await self.result_text(settled, actual, result, pnl, stats)
            )
            self._set_snapshot(
                telegram_status=f"OK • đã gửi kết quả {datetime.now(self.timezone):%H:%M:%S}",
                error="",
            )
        except Exception as exc:
            self.telegram.last_error = str(exc)
            self._set_snapshot(error=f"Telegram kết quả: {exc}")
            log.exception("Không gửi được Telegram result; giữ thứ tự result -> entry")
            return False

        await self.db.execute(
            "UPDATE pattern_signals SET result_notified=1 WHERE id=?",
            (int(row["id"]),),
        )
        await self.db.commit()
        return True

    async def _process_closed_candle(
        self,
        candle: ClosedCandle,
        candles: list[ClosedCandle],
        *,
        allow_signal: bool,
    ) -> None:
        assert self.db is not None
        result_message_ready = await self._settle_for_candle(candle)
        if not result_message_ready:
            # Retry the result first on the next poll. Never put a fresh BUY card
            # ahead of the WIN/LOSS card for the candle that has just finished.
            return
        window = self._window_ending_at(candle, candles)
        if window:
            self._update_market_preview(window)
        if allow_signal and len(window) == 5:
            await self._create_signal_from_window(window)
        await self._db_set("last_source_open_time", candle.open_time)
        await self.db.commit()

    async def _create_signal_from_window(self, window: list[ClosedCandle]) -> None:
        assert self.db is not None
        colors = [item.color for item in window]
        direction = recognize_five_candle_pattern(colors)
        if direction is None:
            self._set_snapshot(last_signal=None)
            return
        pattern = "".join(value or "D" for value in colors)
        source_open = window[-1].open_time
        cursor = await self.db.execute(
            "SELECT id FROM pattern_signals WHERE source_open_time=?", (source_open,)
        )
        existing = await cursor.fetchone()
        if existing:
            return

        step = int(await self._db_get("current_step", "1"))
        bet1 = float(await self._db_get("bet1", str(self.config.base_bet)))
        bet2 = float(await self._db_get("bet2", str(getattr(self.config, "second_bet", self.config.base_bet * 2))))
        bet = bet2 if step == 2 else bet1
        target_open = source_open + INTERVAL_MS
        created_at = int(datetime.now(timezone.utc).timestamp() * 1000)
        await self.db.execute(
            "INSERT INTO pattern_signals(source_open_time,target_open_time,pattern,direction,bet_step,bet_amount,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (source_open, target_open, pattern, direction, step, bet, created_at),
        )
        await self.db.commit()

        signal = {
            "pattern": pattern,
            "direction": direction,
            "bet_step": step,
            "bet_amount": bet,
            "target_open_time": target_open,
            "target_close_time": target_open + INTERVAL_MS,
        }
        self._set_snapshot(last_signal=signal, recommendation=direction)
        telegram_enabled = await self._db_get("telegram_enabled", "1") == "1"
        if telegram_enabled:
            try:
                await self.telegram.send(await self.signal_text(signal))
                self._set_snapshot(
                    telegram_status=f"OK • đã gửi lệnh {datetime.now(self.timezone):%H:%M:%S}",
                    error="",
                )
                log.info("Telegram signal sent: %s -> %s", pattern, direction)
            except Exception as exc:
                self.telegram.last_error = str(exc)
                self._set_snapshot(error=f"Telegram: {exc}")
                log.exception("Không gửi được Telegram signal")

    async def signal_text(self, signal: dict[str, Any]) -> str:
        direction = str(signal["direction"])
        pattern = str(signal["pattern"])
        icons = " ".join(COLOR_ICON.get(c, "⚪") for c in pattern)
        frame = self._frame_text(int(signal["target_open_time"]), int(signal["target_close_time"]))
        day = self._local_day(int(signal["target_open_time"]))
        stats = await self._day_stats(day)
        return (
            f"{COLOR_ICON[direction]} <b>MUA {COLOR_LABEL[direction]}</b>\n"
            f"⏰ Khung giờ: <b>{frame}</b>\n"
            f"🕯 5 kết quả Prediction gần nhất: {icons}\n"
            f"💵 Lệnh {int(signal['bet_step'])}: <b>{_money(float(signal['bet_amount']))} USDT</b>\n"
            f"📊 Thắng: <b>{stats['wins']}</b> • Thua: <b>{stats['losses']}</b>"
        )

    async def result_text(
        self,
        settled: dict[str, Any],
        actual_color: str | None,
        result: str,
        pnl: float,
        stats: dict[str, float | int],
    ) -> str:
        direction = str(settled["direction"])
        frame = self._frame_text(
            int(settled["target_open_time"]), int(settled["target_close_time"])
        )
        if result == "WIN":
            headline = "✅ <b>THẮNG</b>"
        elif result == "LOSS":
            headline = "❌ <b>THUA</b>"
        else:
            headline = "⚪ <b>HÒA / DOJI</b>"
        actual_icon = COLOR_ICON.get(str(actual_color), "⚪")
        actual_label = COLOR_LABEL.get(str(actual_color), "DOJI")
        return (
            f"{headline} • MUA {COLOR_LABEL[direction]}\n"
            f"⏰ Khung giờ: <b>{frame}</b>\n"
            f"🕯 Nến kết quả: {actual_icon} <b>{actual_label}</b>\n"
            f"💵 Lệnh {int(settled['bet_step'])}: {_money(float(settled['bet_amount']))} USDT"
            f" • P/L: <b>{float(pnl):+.2f} USDT</b>\n"
            f"📊 Thắng: <b>{int(stats['wins'])}</b> • Thua: <b>{int(stats['losses'])}</b>"
        )

    async def status_text(self) -> str:
        snap = self.snapshot()
        return (
            f"BOSS V{APP_VERSION} • {snap['symbol']}\n"
            f"Nguồn: {snap['source_label']}\n"
            f"Mẫu: {snap['pattern']} • Khung: {snap['frame']}\n"
            f"Hôm nay: {_money(snap['daily_pnl'])} USDT"
        )

    async def test_telegram(self) -> int:
        message_id = await self.telegram.send(
            f"🧪 <b>TEST TELEGRAM BOSS V{APP_VERSION}</b>\n"
            f"✅ Telegram đang nhận tin từ Boss.\n"
            f"📡 Nguồn màu: {self.snapshot()['source_label']}"
        )
        self._set_snapshot(
            telegram_status=f"OK • test thành công {datetime.now(self.timezone):%H:%M:%S}",
            error="",
        )
        return message_id

    async def update_settings(
        self,
        *,
        bet1: float,
        bet2: float,
        start_balance: float,
        payout_percent: float,
        telegram_enabled: bool,
    ) -> None:
        if bet1 <= 0 or bet2 <= 0:
            raise ValueError("Tiền Lệnh 1 và Lệnh 2 phải lớn hơn 0")
        if start_balance < 0:
            raise ValueError("Vốn đầu ngày không được âm")
        if not 0 < payout_percent <= 200:
            raise ValueError("Tỷ lệ trả thưởng phải trong khoảng 0–200%")
        async with self._settings_lock:
            assert self.db is not None
            payout_rate = payout_percent / 100.0
            await self._db_set("bet1", bet1)
            await self._db_set("bet2", bet2)
            await self._db_set("payout_rate", payout_rate)
            await self._db_set("telegram_enabled", 1 if telegram_enabled else 0)
            await self._db_set("default_start_balance", start_balance)
            day = self._local_day()
            await self._ensure_day(day)
            await self.db.execute(
                "UPDATE pattern_daily SET start_balance=?, end_balance=?+pnl, updated_at=? WHERE day=?",
                (start_balance, start_balance, int(datetime.now(timezone.utc).timestamp() * 1000), day),
            )
            await self.db.commit()
            await self._refresh_snapshot()

    async def _refresh_snapshot(self) -> None:
        assert self.db is not None
        today = self._local_day()
        await self._ensure_day(today)
        cursor = await self.db.execute("SELECT * FROM pattern_daily WHERE day=?", (today,))
        day_row = await cursor.fetchone()
        cursor = await self.db.execute(
            "SELECT * FROM pattern_daily WHERE day < ? ORDER BY day DESC LIMIT 1", (today,)
        )
        previous = await cursor.fetchone()
        cursor = await self.db.execute(
            "SELECT target_open_time,pattern,direction,bet_step,bet_amount,result,actual_color,pnl "
            "FROM pattern_signals WHERE result IN ('WIN','LOSS') "
            "ORDER BY target_open_time DESC LIMIT 100"
        )
        history_rows = list(reversed(await cursor.fetchall()))
        history = ["V" if row["result"] == "WIN" else "X" for row in history_rows]
        details = []
        for row in history_rows:
            local = datetime.fromtimestamp(int(row["target_open_time"]) / 1000, self.timezone)
            details.append({
                "time": local.strftime("%d/%m %H:%M"),
                "mark": "V" if row["result"] == "WIN" else "X",
                "pattern": str(row["pattern"]),
                "direction": str(row["direction"]),
                "bet_step": int(row["bet_step"]),
                "bet_amount": float(row["bet_amount"]),
                "actual_color": str(row["actual_color"] or ""),
                "pnl": float(row["pnl"]),
            })
        bet1 = float(await self._db_get("bet1", str(self.config.base_bet)))
        bet2 = float(await self._db_get("bet2", str(getattr(self.config, "second_bet", self.config.base_bet * 2))))
        current_step = int(await self._db_get("current_step", "1"))
        telegram_enabled = await self._db_get("telegram_enabled", "1") == "1"
        payout = float(await self._db_get("payout_rate", str(self.config.payout_rate))) * 100.0
        previous_payload = None
        if previous:
            previous_payload = {
                "day": str(previous["day"]),
                "start_balance": float(previous["start_balance"]),
                "pnl": float(previous["pnl"]),
                "end_balance": float(previous["end_balance"]),
                "wins": int(previous["wins"]),
                "losses": int(previous["losses"]),
            }
        self._set_snapshot(
            current_step=current_step,
            next_bet=bet2 if current_step == 2 else bet1,
            bet1=bet1,
            bet2=bet2,
            payout_percent=payout,
            telegram_enabled=telegram_enabled,
            day=today,
            start_balance=float(day_row["start_balance"]),
            daily_pnl=float(day_row["pnl"]),
            end_balance=float(day_row["end_balance"]),
            wins=int(day_row["wins"]),
            losses=int(day_row["losses"]),
            history=history,
            history_details=details,
            previous_day=previous_payload,
        )

    async def _poll_once(self) -> None:
        candles = await self._fetch_closed(40)
        if len(candles) < 5:
            raise RuntimeError("Không lấy đủ dữ liệu M5")
        latest = candles[-1]
        stored = int(await self._db_get("last_source_open_time", "0"))
        if latest.open_time > stored:
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            for candle in candles:
                if candle.open_time <= stored:
                    continue
                is_latest = candle.open_time == latest.open_time
                allow_signal = is_latest and now_ms - candle.close_time <= FRESH_SIGNAL_GRACE_MS
                await self._process_closed_candle(candle, candles, allow_signal=allow_signal)
        else:
            await self._settle_pending_from(candles[-8:])
        self._update_market_preview(candles[-5:])
        await self._refresh_snapshot()
        status = (
            "Đang theo dõi Binance Prediction BTC Up/Down 5m"
            if self.config.prediction_source == "predictfun"
            else "Đang theo dõi nến M5 Binance Futures"
        )
        source_error = self.prediction_history.last_error if self.prediction_history else ""
        self._set_snapshot(connected=True, status=status, source_error=source_error, error="")

    async def run(self) -> None:
        try:
            await self.setup()
            if self.config.mobile_enabled:
                try:
                    from mobile_web import MobileWebServer
                    self.mobile_server = MobileWebServer(
                        self, self.config.mobile_host, self.config.mobile_port
                    )
                    await self.mobile_server.start()
                    self._set_snapshot(
                        mobile_status=f"Đang chạy cổng {self.config.mobile_port}"
                    )
                except Exception as exc:
                    log.exception("Không mở được iPhone dashboard")
                    self._set_snapshot(mobile_status=f"Lỗi: {exc}")
                    self.mobile_server = None
            while not self.stop_event.is_set():
                try:
                    await self._poll_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.exception("V4.1 polling error")
                    source_error = self.prediction_history.last_error if self.prediction_history else ""
                    self._set_snapshot(
                        connected=False,
                        status="Mất kết nối, đang thử lại...",
                        error=str(exc),
                        source_error=source_error,
                    )
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass
        finally:
            if self.mobile_server is not None:
                try:
                    await self.mobile_server.stop()
                except Exception:
                    log.exception("Không dừng được iPhone dashboard")
            await self.close()


TradingSignalBotV3 = PatternSignalBot
