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


@dataclass(frozen=True)
class Config:
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    symbol: str = field(default_factory=lambda: os.getenv("SYMBOL", "BTCUSDT").upper())
    base_bet: float = field(default_factory=lambda: _float("BASE_BET", 1.0))
    payout_rate: float = field(default_factory=lambda: _float("PAYOUT_RATE", 0.80))
    decision_second: int = field(default_factory=lambda: _int("DECISION_SECOND", 18))
    max_bet: float = field(default_factory=lambda: _float("MAX_BET", 50.0))
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "data/bot.db"))
    timezone_name: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    app_password: str = field(default_factory=lambda: os.getenv("APP_PASSWORD", "123"))

    @property
    def timezone(self):
        try:
            return ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError:
            # Bản Windows/PyInstaller vẫn chạy đúng giờ Việt Nam nếu dữ liệu
            # IANA bị thiếu hoặc bị phần mềm bảo mật loại khỏi gói cài đặt.
            if self.timezone_name == "Asia/Ho_Chi_Minh":
                return timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")
            raise

    def validate(self) -> None:
        if not self.telegram_token or not self.telegram_chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID là bắt buộc")
        if self.base_bet <= 0 or self.base_bet > self.max_bet:
            raise ValueError("BASE_BET phải lớn hơn 0 và không vượt MAX_BET")
        if not 0 < self.payout_rate <= 2:
            raise ValueError("PAYOUT_RATE phải nằm trong khoảng (0, 2]")
        if not 10 <= self.decision_second <= 20:
            raise ValueError("DECISION_SECOND phải nằm trong khoảng 10–20")
