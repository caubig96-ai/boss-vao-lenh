import os
from dataclasses import dataclass


def _bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


def _float(name, default):
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default


@dataclass
class Settings:
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    symbol: str = os.getenv("SYMBOL", "BTCUSDT")
    interval: str = os.getenv("INTERVAL", "5m")
    binance_base_url: str = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///boss_vao_lenh.db")
    model_threshold: float = _float("MODEL_THRESHOLD", 0.55)
    enable_auto_consensus: bool = _bool("ENABLE_AUTO_CONSENSUS", True)
    auto_consensus_min_agreement: int = _int("AUTO_CONSENSUS_MIN_AGREEMENT", 2)
    auto_consensus_min_confidence: float = _float("AUTO_CONSENSUS_MIN_CONFIDENCE", 0.58)
    auto_consensus_lookback: int = _int("AUTO_CONSENSUS_LOOKBACK", 100)
    auto_consensus_min_samples: int = _int("AUTO_CONSENSUS_MIN_SAMPLES", 30)
    auto_consensus_require_last_loss: bool = _bool("AUTO_CONSENSUS_REQUIRE_LAST_LOSS", True)


settings = Settings()
