from __future__ import annotations

import desktop_v35 as ui
from runtime_v351 import APP_VERSION, TradingSignalBotV3


# Reuse the Binance-Kline-only V3.5 chart while swapping in V3.5.1 signal logic.
ui.APP_VERSION = APP_VERSION
ui.desktop.APP_VERSION = APP_VERSION
ui.desktop.TradingSignalBotV3 = TradingSignalBotV3


if __name__ == "__main__":
    ui.desktop.shutdown_legacy_v2()
    _mutex = ui.desktop.acquire_single_instance()
    ui.BinanceKlineTrayApplication().run()
