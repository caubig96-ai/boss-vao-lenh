from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Config:
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    symbol: str = os.getenv("SYMBOL", "BTCUSDT").upper()
    base_bet: float = _float("BASE_BET", 1.0)
    payout_rate: float = _float("PAYOUT_RATE", 0.80)
    min_confidence: float = _float("MIN_CONFIDENCE", 0.56)
    decision_second: int = _int("DECISION_SECOND", 18)
    max_bet: float = _float("MAX_BET", 50.0)
    database_path: str = os.getenv("DATABASE_PATH", "data/bot.db")
    timezone_name: str = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    app_password: str = os.getenv("APP_PASSWORD", "123")

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def validate(self) -> None:
        if not self.telegram_token or not self.telegram_chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID là bắt buộc")
        if self.base_bet <= 0 or self.base_bet > self.max_bet:
            raise ValueError("BASE_BET phải lớn hơn 0 và không vượt MAX_BET")
        if not 0 < self.payout_rate <= 2:
            raise ValueError("PAYOUT_RATE phải nằm trong khoảng (0, 2]")
        if not 0.5 <= self.min_confidence <= 0.95:
            raise ValueError("MIN_CONFIDENCE phải nằm trong khoảng [0.5, 0.95]")
        if not 10 <= self.decision_second <= 20:
            raise ValueError("DECISION_SECOND phải nằm trong khoảng 10–20")
