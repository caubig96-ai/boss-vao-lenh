from __future__ import annotations

import asyncio
import logging
import os
import signal
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DEFAULT_CLOUD_ENV = ROOT / ".env.cloud"
DEFAULT_CLOUD_DB = ROOT / "data" / "cloud-bot.db"
DEFAULT_CLOUD_LOG = ROOT / "logs" / "cloud-v4.log"


def load_cloud_environment(env_file: str | Path | None = None) -> Path:
    path = Path(env_file or os.getenv("CLOUD_ENV_FILE", str(DEFAULT_CLOUD_ENV))).expanduser().resolve()
    if path.is_file():
        load_dotenv(path, override=False)
    token = os.getenv("CLOUD_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("CLOUD_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise ValueError("Cloud cần CLOUD_TELEGRAM_BOT_TOKEN và CLOUD_TELEGRAM_CHAT_ID trong .env.cloud.")
    existing_desktop_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if existing_desktop_token and existing_desktop_token == token:
        raise ValueError("Cloud và Windows phải dùng 2 Telegram bot token khác nhau.")
    mappings = {
        "CLOUD_TELEGRAM_BOT_TOKEN": "TELEGRAM_BOT_TOKEN",
        "CLOUD_TELEGRAM_CHAT_ID": "TELEGRAM_CHAT_ID",
        "CLOUD_SYMBOL": "SYMBOL",
        "CLOUD_BASE_BET": "BASE_BET",
        "CLOUD_SECOND_BET": "SECOND_BET",
        "CLOUD_START_BALANCE": "START_BALANCE",
        "CLOUD_PAYOUT_RATE": "PAYOUT_RATE",
        "CLOUD_DECISION_SECOND": "DECISION_SECOND",
        "CLOUD_MAX_BET": "MAX_BET",
        "CLOUD_TIMEZONE": "TIMEZONE",
        "CLOUD_LOG_LEVEL": "LOG_LEVEL",
        "CLOUD_PREDICTION_SOURCE": "PREDICTION_SOURCE",
        "CLOUD_PREDICT_API_BASE": "PREDICT_API_BASE",
        "CLOUD_PREDICT_API_KEY": "PREDICT_API_KEY",
        "CLOUD_MOBILE_ENABLED": "MOBILE_ENABLED",
        "CLOUD_MOBILE_HOST": "MOBILE_HOST",
        "CLOUD_MOBILE_PORT": "MOBILE_PORT",
    }
    for cloud_name, standard_name in mappings.items():
        value = os.getenv(cloud_name, "").strip()
        if value:
            os.environ[standard_name] = value
    os.environ["DATABASE_PATH"] = os.getenv("CLOUD_DATABASE_PATH", "").strip() or str(DEFAULT_CLOUD_DB)
    return path


def configure_logging() -> None:
    DEFAULT_CLOUD_LOG.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, os.getenv("CLOUD_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(DEFAULT_CLOUD_LOG, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[file_handler, stream_handler], force=True)


async def async_main() -> None:
    load_cloud_environment()
    configure_logging()
    from config import Config
    from runtime_v4 import APP_VERSION, PatternSignalBot

    class CloudPatternSignalBot(PatternSignalBot):
        async def signal_text(self, signal):
            return "☁️ <b>CLOUD</b>\n" + await super().signal_text(signal)

    config = Config()
    config.validate()
    bot = CloudPatternSignalBot(config)
    logging.getLogger(__name__).info("Starting cloud Boss V%s", APP_VERSION)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bot.stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass
    await bot.run()


if __name__ == "__main__":
    asyncio.run(async_main())
