from __future__ import annotations

import desktop_v3 as desktop
from runtime_v34 import APP_VERSION, TradingSignalBotV3


# Reuse the stable V3 desktop UI, but inject the V3.4 runtime and synchronize
# every visible desktop version label before the app is created.
desktop.APP_VERSION = APP_VERSION
desktop.TradingSignalBotV3 = TradingSignalBotV3


if __name__ == "__main__":
    desktop.shutdown_legacy_v2()
    _mutex = desktop.acquire_single_instance()
    desktop.TrayApplication().run()
