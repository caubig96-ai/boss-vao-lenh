from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

import desktop_v35 as desktop35
from runtime_v376 import APP_VERSION, TradingSignalBotV3


desktop35.APP_VERSION = APP_VERSION
desktop35.desktop.APP_VERSION = APP_VERSION
desktop35.desktop.TradingSignalBotV3 = TradingSignalBotV3


class VisibleStartupApplication(desktop35.BinanceKlineTrayApplication):
    def __init__(self):
        super().__init__()
        self._startup_error_shown = False
        # Start silently in the Windows system tray. The password dialog is
        # requested only when the user opens the tool from the tray icon (or
        # sends the local OPEN command handled by the base TrayApplication).
        self.root.after(900, self._watch_startup)

    def _watch_startup(self) -> None:
        if self.engine.error and not self._startup_error_shown:
            self._startup_error_shown = True
            log_path = desktop35.desktop.persistent_root() / "logs" / "boss-v3.log"
            messagebox.showerror(
                f"Boss Vào Lệnh V{APP_VERSION} - Engine không chạy",
                f"Engine đã dừng: {self.engine.error}\n\nLog: {log_path}",
            )
            return
        self.root.after(900, self._watch_startup)


if __name__ == "__main__":
    try:
        desktop35.desktop.shutdown_legacy_v2()
        _mutex = desktop35.desktop.acquire_single_instance()
        VisibleStartupApplication().run()
    except Exception as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            f"Boss Vào Lệnh V{APP_VERSION} - Lỗi khởi động",
            f"{type(exc).__name__}: {exc}",
        )
        root.destroy()
        raise
