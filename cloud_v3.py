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
DEFAULT_CLOUD_LOG = ROOT / "logs" / "cloud-v3.log"


def load_cloud_environment(env_file: str | Path | None = None) -> Path:
    """Load a cloud-only environment without reusing the Windows Telegram bot.

    The cloud instance intentionally requires CLOUD_TELEGRAM_* variables. This
    prevents a cloned repo that also contains a normal .env from accidentally
    polling the same Telegram bot token as the Windows instance.
    """
    path = Path(env_file or os.getenv("CLOUD_ENV_FILE", str(DEFAULT_CLOUD_ENV))).expanduser().resolve()
    if path.is_file():
        load_dotenv(path, override=False)

    token = os.getenv("CLOUD_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("CLOUD_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise ValueError(
            "Cloud cần CLOUD_TELEGRAM_BOT_TOKEN và CLOUD_TELEGRAM_CHAT_ID trong .env.cloud. "
            "Hãy dùng Telegram Bot riêng cho CLOUD để không xung đột polling với bản Windows."
        )

    mappings = {
        "CLOUD_TELEGRAM_BOT_TOKEN": "TELEGRAM_BOT_TOKEN",
        "CLOUD_TELEGRAM_CHAT_ID": "TELEGRAM_CHAT_ID",
        "CLOUD_SYMBOL": "SYMBOL",
        "CLOUD_BASE_BET": "BASE_BET",
        "CLOUD_PAYOUT_RATE": "PAYOUT_RATE",
        "CLOUD_DECISION_SECOND": "DECISION_SECOND",
        "CLOUD_MAX_BET": "MAX_BET",
        "CLOUD_TIMEZONE": "TIMEZONE",
        "CLOUD_LOG_LEVEL": "LOG_LEVEL",
    }
    for cloud_name, standard_name in mappings.items():
        value = os.getenv(cloud_name, "").strip()
        if value:
            os.environ[standard_name] = value

    cloud_db = os.getenv("CLOUD_DATABASE_PATH", "").strip()
    os.environ["DATABASE_PATH"] = cloud_db or str(DEFAULT_CLOUD_DB)
    return path


def configure_logging() -> None:
    DEFAULT_CLOUD_LOG.parent.mkdir(parents=True, exist_ok=True)
    level_name = os.getenv("CLOUD_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        DEFAULT_CLOUD_LOG,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[file_handler, stream_handler], force=True)


async def async_main() -> None:
    load_cloud_environment()
    configure_logging()

    from config import Config
    from runtime_v3 import APP_VERSION, TradingSignalBotV3

    class CloudTradingSignalBot(TradingSignalBotV3):
        async def signal_text(self, prediction):
            return "☁️ <b>CLOUD</b>\n" + await super().signal_text(prediction)

        async def result_text(self, row, close_price: float, result: str, pnl: float) -> str:
            return "☁️ <b>CLOUD</b>\n" + await super().result_text(row, close_price, result, pnl)

        async def status_text(self) -> str:
            return "☁️ <b>CLOUD</b>\n" + await super().status_text()

        async def safe_startup_message(self) -> None:
            try:
                enabled = await self.db.get("manual_enabled", "1") == "1"
                await self.telegram.send(
                    f"☁️ <b>CLOUD • BOT V{APP_VERSION} ĐÃ KHỞI ĐỘNG</b>\n"
                    "Bản cloud độc lập đang chạy 24/7: WebSocket + REST dự phòng + watchdog M5.",
                    enabled=enabled,
                )
            except Exception as exc:
                self.telegram.last_error = str(exc)
                logging.getLogger("boss-vao-lenh-cloud").warning(
                    "Startup Telegram send failed; market engine continues: %s", exc
                )

    config = Config()
    config.validate()
    bot = CloudTradingSignalBot(config)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bot.stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass
    await bot.run()


if __name__ == "__main__":
    asyncio.run(async_main())
