from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _default_database_path() -> str:
    """Use one stable Windows database so rebuilding/moving the EXE cannot reset stats."""
    if os.name == "nt":
        root = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if root:
            return os.path.join(root, "BossVaoLenh", "data", "bot.db")
    return "data/bot.db"


def _database_path() -> str:
    configured = os.getenv("DATABASE_PATH", "").strip()
    if os.name == "nt":
        if configured and os.path.isabs(configured):
            return configured
        return _default_database_path()
    return configured or _default_database_path()


@dataclass(frozen=True)
class Config:
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    symbol: str = field(default_factory=lambda: os.getenv("SYMBOL", "BTCUSDT").upper())
    base_bet: float = field(default_factory=lambda: _float("BASE_BET", 1.0))
    second_bet: float = field(default_factory=lambda: _float("SECOND_BET", 2.0))
    start_balance: float = field(default_factory=lambda: _float("START_BALANCE", 0.0))
    payout_rate: float = field(default_factory=lambda: _float("PAYOUT_RATE", 0.80))
    decision_second: int = field(default_factory=lambda: _int("DECISION_SECOND", 10))
    max_bet: float = field(default_factory=lambda: _float("MAX_BET", 50.0))
    database_path: str = field(default_factory=_database_path)
    timezone_name: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    app_password: str = field(default_factory=lambda: os.getenv("APP_PASSWORD", "123"))

    # V4.1 defaults to the Prediction-market result source. "futures" remains
    # available only as an explicit diagnostic fallback.
    prediction_source: str = field(default_factory=lambda: os.getenv("PREDICTION_SOURCE", "predictfun").strip().lower())
    predict_api_base: str = field(default_factory=lambda: os.getenv("PREDICT_API_BASE", "https://api.predict.fun").strip())
    predict_api_key: str = field(default_factory=lambda: os.getenv("PREDICT_API_KEY", "").strip())

    # Read-only iPhone dashboard served by the same Boss process.
    mobile_enabled: bool = field(default_factory=lambda: _bool("MOBILE_ENABLED", True))
    mobile_host: str = field(default_factory=lambda: os.getenv("MOBILE_HOST", "0.0.0.0").strip())
    mobile_port: int = field(default_factory=lambda: _int("MOBILE_PORT", 8765))
    mobile_password: str = field(
        default_factory=lambda: os.getenv(
            "MOBILE_PASSWORD", os.getenv("APP_PASSWORD", "123")
        )
    )

    @property
    def timezone(self):
        try:
            return ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError:
            if self.timezone_name == "Asia/Ho_Chi_Minh":
                return timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")
            raise

    def validate(self) -> None:
        if not self.telegram_token or not self.telegram_chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID là bắt buộc")
        if self.base_bet <= 0 or self.base_bet > self.max_bet:
            raise ValueError("BASE_BET phải lớn hơn 0 và không vượt MAX_BET")
        if self.second_bet <= 0:
            raise ValueError("SECOND_BET phải lớn hơn 0")
        if self.start_balance < 0:
            raise ValueError("START_BALANCE không được âm")
        if not 0 < self.payout_rate <= 2:
            raise ValueError("PAYOUT_RATE phải nằm trong khoảng (0, 2]")
        if not 10 <= self.decision_second <= 20:
            raise ValueError("DECISION_SECOND phải nằm trong khoảng 10–20")
        if self.prediction_source not in {"predictfun", "futures"}:
            raise ValueError("PREDICTION_SOURCE chỉ nhận predictfun hoặc futures")
        if not 1 <= self.mobile_port <= 65535:
            raise ValueError("MOBILE_PORT không hợp lệ")
        if self.mobile_enabled and len(self.mobile_password) < 4:
            raise ValueError("MOBILE_PASSWORD phải có ít nhất 4 ký tự")
