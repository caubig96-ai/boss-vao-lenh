from __future__ import annotations

import desktop_v35 as desktop35
from runtime_v354 import APP_VERSION, TradingSignalBotV3


desktop35.APP_VERSION = APP_VERSION
desktop35.desktop.APP_VERSION = APP_VERSION
desktop35.desktop.TradingSignalBotV3 = TradingSignalBotV3


if __name__ == "__main__":
    desktop35.desktop.shutdown_legacy_v2()
    _mutex = desktop35.desktop.acquire_single_instance()
    desktop35.BinanceKlineTrayApplication().run()
