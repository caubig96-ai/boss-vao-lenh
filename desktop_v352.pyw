from __future__ import annotations

import desktop_v35 as desktop35
from runtime_v352 import APP_VERSION, TradingSignalBotV3


# Reuse the Binance Kline-only chart from V3.5 and inject the V3.5.2 runtime.
desktop35.APP_VERSION = APP_VERSION
desktop35.desktop.APP_VERSION = APP_VERSION
desktop35.desktop.TradingSignalBotV3 = TradingSignalBotV3


if __name__ == "__main__":
    desktop35.desktop.shutdown_legacy_v2()
    _mutex = desktop35.desktop.acquire_single_instance()
    desktop35.BinanceKlineTrayApplication().run()
