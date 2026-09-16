from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

import pystray

import desktop_v35 as desktop35
from runtime_v376 import APP_VERSION, TradingSignalBotV3


desktop35.APP_VERSION = APP_VERSION
desktop35.desktop.APP_VERSION = APP_VERSION
desktop35.desktop.TradingSignalBotV3 = TradingSignalBotV3


class VisibleStartupApplication(desktop35.BinanceKlineTrayApplication):
    def __init__(self):
        self._tray_thread: threading.Thread | None = None
        self._exiting = False
        super().__init__()
        self._startup_error_shown = False
        # Start silently in the Windows system tray. The password dialog is
        # requested only when the user opens the tool from the tray icon (or
        # sends the local OPEN command handled by the base TrayApplication).
        self.root.after(1200, self._ensure_tray_running)
        self.root.after(900, self._watch_startup)

    def _create_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem(f"Mở Boss V{APP_VERSION}", self._tray_open, default=True),
            pystray.MenuItem("Dừng gửi tín hiệu", self._tray_pause),
            pystray.MenuItem("Chạy gửi tín hiệu", self._tray_resume),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Thoát hoàn toàn", self._tray_exit),
        )
        self.tray = pystray.Icon(
            desktop35.desktop.APP_NAME,
            self._icon_image(),
            f"Boss Vào Lệnh V{APP_VERSION}",
            menu,
        )
        self._tray_thread = threading.Thread(
            target=self._run_tray_guarded,
            name="tray-icon-v376",
            daemon=True,
        )
        self._tray_thread.start()

    def _run_tray_guarded(self) -> None:
        try:
            if self.tray:
                self.tray.run()
        except Exception:
            desktop35.desktop.log.exception("V3.7.6 system tray stopped unexpectedly")

    def _ensure_tray_running(self) -> None:
        if self._exiting:
            return
        if self._tray_thread is None or not self._tray_thread.is_alive():
            desktop35.desktop.log.warning("V3.7.6 tray missing; recreating system tray icon")
            try:
                if self.tray:
                    self.tray.stop()
            except Exception:
                pass
            self._create_tray()
        self.root.after(3000, self._ensure_tray_running)

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

    def exit_application_force(self) -> None:
        self._exiting = True
        super().exit_application_force()


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
