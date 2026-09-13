from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import socket
import sys
import threading
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox, ttk

import pystray
from PIL import Image, ImageDraw
from dotenv import load_dotenv

APP_NAME = "BossVaoLenh"
APP_VERSION = "3.0.0"
MUTEX_NAME = r"Local\BossVaoLenh_V3_SingleInstance"
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 45874
LEGACY_CONTROL_PORT = 45873


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = app_directory()
os.chdir(BASE_DIR)
for candidate in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
    if candidate.is_file():
        load_dotenv(candidate, override=False)
        break

from config import Config  # noqa: E402
from runtime_v3 import TradingSignalBotV3  # noqa: E402


def persistent_root() -> Path:
    root = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
    return Path(root) / "BossVaoLenh"


def configure_logging() -> None:
    log_dir = persistent_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "boss-v3.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)


configure_logging()
log = logging.getLogger(__name__)


class BackgroundBot:
    def __init__(self):
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.bot: TradingSignalBotV3 | None = None
        self.error = ""
        self.ready = threading.Event()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, name="trading-engine-v3", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            config = Config()
            config.validate()
            self.bot = TradingSignalBotV3(config)
            self.ready.set()
            self.loop.run_until_complete(self.bot.run())
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            log.exception("Trading engine V3 stopped")
            self.ready.set()
        finally:
            try:
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
            except Exception:
                pass
            self.loop.close()

    def submit(self, coroutine):
        if not self.loop or not self.thread or not self.thread.is_alive():
            raise RuntimeError("Bộ máy chưa chạy")
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def stop(self) -> None:
        if self.loop and self.bot:
            self.loop.call_soon_threadsafe(self.bot.stop_event.set)
        if self.thread:
            self.thread.join(timeout=8)


class TrayApplication:
    def __init__(self):
        self.config = Config()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(f"Boss Vào Lệnh V{APP_VERSION}")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_dashboard)
        self.engine = BackgroundBot()
        self.tray: pystray.Icon | None = None
        self.dashboard: tk.Toplevel | None = None
        self.m1_chart: tk.Canvas | None = None
        self.m5_chart: tk.Canvas | None = None
        self.health_var = tk.StringVar(value=f"V{APP_VERSION} • đang khởi động")
        self.price_var = tk.StringVar(value="PRICE --")
        self.tick_var = tk.StringVar(value="TICKS 0")
        self.analysis_text: tk.Text | None = None
        self._register_autostart()
        self._start_control_server()
        self._create_tray()
        if self.config.telegram_token and self.config.telegram_chat_id:
            self.engine.start()
        else:
            self.root.after(200, self.show_config_missing)
        self.root.after(1000, self._check_engine)

    def show_config_missing(self) -> None:
        messagebox.showerror(
            "Thiếu cấu hình Telegram",
            "Không tìm thấy TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.\n\n"
            "V3 đọc .env cạnh file EXE hoặc ở thư mục cha. Hãy đặt lại file .env rồi mở tool.",
        )

    def _start_control_server(self) -> None:
        def serve():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    server.bind((CONTROL_HOST, CONTROL_PORT))
                    server.listen(2)
                    while True:
                        connection, _ = server.accept()
                        with connection:
                            command = connection.recv(32).decode("ascii", errors="ignore").strip()
                        if command == "OPEN":
                            self.root.after(0, self.request_password)
                        elif command == "EXIT":
                            self.root.after(0, self.exit_application_force)
                            return
            except OSError as exc:
                log.warning("Control server: %s", exc)
        threading.Thread(target=serve, name="local-control-v3", daemon=True).start()

    def _register_autostart(self) -> None:
        if os.name != "nt":
            return
        try:
            import winreg
            if getattr(sys, "frozen", False):
                command = f'"{sys.executable}"'
            else:
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                command = f'"{pythonw}" "{Path(__file__).resolve()}"'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        except Exception as exc:
            log.warning("Autostart registration failed: %s", exc)

    @staticmethod
    def _icon_image() -> Image.Image:
        image = Image.new("RGB", (64, 64), "#111827")
        draw = ImageDraw.Draw(image)
        draw.ellipse((6, 6, 58, 58), fill="#f59e0b")
        draw.text((18, 14), "B3", fill="white", stroke_width=1)
        draw.polygon([(18, 46), (29, 32), (37, 38), (50, 20), (50, 32), (37, 49), (29, 42)], fill="#16a34a")
        return image

    def _create_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Mở bảng V3", self._tray_open, default=True),
            pystray.MenuItem("Dừng gửi tín hiệu", self._tray_pause),
            pystray.MenuItem("Chạy gửi tín hiệu", self._tray_resume),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Thoát hoàn toàn", self._tray_exit),
        )
        self.tray = pystray.Icon(APP_NAME, self._icon_image(), f"Boss Vào Lệnh V{APP_VERSION}", menu)
        threading.Thread(target=self.tray.run, name="tray-icon", daemon=True).start()

    def _tray_open(self, icon=None, item=None) -> None:
        self.root.after(0, self.request_password)

    def _set_manual(self, enabled: bool) -> None:
        bot = self.engine.bot
        if not bot:
            return
        try:
            self.engine.submit(bot.db.set("manual_enabled", 1 if enabled else 0))
            if enabled:
                self.engine.submit(bot.db.set("risk_pause_until", 0))
                self.engine.submit(bot.db.set("risk_cycle_losses", 0))
        except Exception as exc:
            messagebox.showerror("Lỗi", str(exc))

    def _tray_pause(self, icon=None, item=None) -> None:
        self.root.after(0, lambda: self._set_manual(False))

    def _tray_resume(self, icon=None, item=None) -> None:
        self.root.after(0, lambda: self._set_manual(True))

    def _tray_exit(self, icon=None, item=None) -> None:
        self.root.after(0, self.exit_application)

    def _check_engine(self) -> None:
        bot = self.engine.bot
        if self.engine.error:
            self.health_var.set(f"V{APP_VERSION} • ENGINE STOPPED • {self.engine.error}")
        elif bot and self.engine.thread and self.engine.thread.is_alive():
            trade_age = bot._age(bot.last_trade_rx_mono)
            rest_age = bot._age(bot.last_rest_ok_mono)
            if trade_age is not None and trade_age <= 2.5:
                source = "WS TICK"
            elif rest_age is not None and rest_age <= 3.5:
                source = "REST FALLBACK"
            else:
                source = "NO MARKET DATA"
            self.health_var.set(f"V{APP_VERSION} • {source} • decision: {bot.last_decision_state}")
            self.price_var.set(f"PRICE {bot.live_price:,.2f}")
            self.tick_var.set(f"TICKS {bot.trade_ticks:,}")
        elif self.config.telegram_token and self.config.telegram_chat_id:
            self.health_var.set(f"V{APP_VERSION} • engine chưa sẵn sàng")
        self.root.after(500, self._check_engine)

    def request_password(self) -> None:
        if not self.config.telegram_token or not self.config.telegram_chat_id:
            self.show_config_missing()
            return
        if self.dashboard and self.dashboard.winfo_exists():
            self.dashboard.deiconify()
            self.dashboard.lift()
            return
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Mở Boss V{APP_VERSION}")
        dialog.geometry("330x165")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        ttk.Label(dialog, text=f"BOSS VÀO LỆNH V{APP_VERSION}", font=("Segoe UI", 14, "bold")).pack(pady=(16, 4))
        ttk.Label(dialog, text="Nhập mật khẩu").pack()
        password = ttk.Entry(dialog, show="•", font=("Segoe UI", 13), justify="center")
        password.pack(fill="x", padx=35, pady=6)
        password.focus_set()

        def submit(event=None):
            if password.get() == self.config.app_password:
                dialog.destroy()
                self.show_dashboard()
            else:
                password.delete(0, tk.END)
                messagebox.showerror("Sai mật khẩu", "Mật khẩu không đúng.", parent=dialog)
        password.bind("<Return>", submit)
        ttk.Button(dialog, text="MỞ TOOL", command=submit).pack(pady=5)

    def show_dashboard(self) -> None:
        if self.dashboard and self.dashboard.winfo_exists():
            self.dashboard.deiconify()
            self.dashboard.lift()
            return
        self.dashboard = tk.Toplevel(self.root)
        self.dashboard.title(f"Boss Vào Lệnh V{APP_VERSION} – Binance Live")
        self.dashboard.geometry("1180x900")
        self.dashboard.minsize(920, 700)
        self.dashboard.protocol("WM_DELETE_WINDOW", self.hide_dashboard)

        header = ttk.Frame(self.dashboard, padding=(12, 10))
        header.pack(fill="x")
        ttk.Label(header, text=f"BOSS VÀO LỆNH V{APP_VERSION}", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self.tick_var, font=("Consolas", 11, "bold")).pack(side="right", padx=12)
        ttk.Label(header, textvariable=self.price_var, font=("Consolas", 12, "bold")).pack(side="right", padx=12)
        ttk.Label(self.dashboard, textvariable=self.health_var, font=("Segoe UI", 10)).pack(fill="x", padx=12)

        notebook = ttk.Notebook(self.dashboard)
        notebook.pack(fill="both", expand=True, padx=12, pady=8)
        chart_tab = ttk.Frame(notebook)
        analysis_tab = ttk.Frame(notebook)
        notebook.add(chart_tab, text="BIỂU ĐỒ LIVE")
        notebook.add(analysis_tab, text="CHẨN ĐOÁN")

        chart_panels = ttk.Panedwindow(chart_tab, orient=tk.VERTICAL)
        chart_panels.pack(fill="both", expand=True)
        m1_frame = ttk.LabelFrame(chart_panels, text="BTCUSDT M1 – LIVE TỪNG TICK")
        m5_frame = ttk.LabelFrame(chart_panels, text="BTCUSDT M5 – LIVE TỪNG TICK")
        chart_panels.add(m1_frame, weight=1)
        chart_panels.add(m5_frame, weight=1)
        self.m1_chart = tk.Canvas(m1_frame, background="#0b0e11", highlightthickness=0)
        self.m5_chart = tk.Canvas(m5_frame, background="#0b0e11", highlightthickness=0)
        self.m1_chart.pack(fill="both", expand=True)
        self.m5_chart.pack(fill="both", expand=True)

        self.analysis_text = tk.Text(analysis_tab, font=("Consolas", 11), wrap="word", state="disabled")
        self.analysis_text.pack(fill="both", expand=True, padx=8, pady=8)

        controls = ttk.Frame(self.dashboard, padding=10)
        controls.pack(fill="x")
        ttk.Button(controls, text="DỪNG GỬI LỆNH", command=lambda: self._set_manual(False)).pack(side="left", padx=4)
        ttk.Button(controls, text="CHẠY + XÓA TẠM NGHỈ", command=lambda: self._set_manual(True)).pack(side="left", padx=4)
        ttk.Button(controls, text="MỞ THƯ MỤC LOG", command=self.open_logs).pack(side="left", padx=4)
        ttk.Button(controls, text="ẨN XUỐNG TRAY", command=self.hide_dashboard).pack(side="right", padx=4)
        self.dashboard.after(100, self._refresh_dashboard)

    def open_logs(self) -> None:
        path = persistent_root() / "logs"
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]

    def hide_dashboard(self) -> None:
        if self.dashboard and self.dashboard.winfo_exists():
            self.dashboard.withdraw()

    @staticmethod
    def _with_live(closed, live):
        rows = list(closed)[-99:]
        if live is None:
            return rows[-100:]
        if rows and rows[-1].open_time == live.open_time:
            rows[-1] = live
        else:
            rows.append(live)
        return rows[-100:]

    def _refresh_dashboard(self) -> None:
        if not self.dashboard or not self.dashboard.winfo_exists():
            return
        self.dashboard.after(100, self._refresh_dashboard)
        if not self.dashboard.winfo_viewable():
            return
        bot = self.engine.bot
        if not bot:
            return
        self._draw_candles(self.m1_chart, self._with_live(bot.m1, bot.live_m1), "M1", bot)
        self._draw_candles(self.m5_chart, self._with_live(bot.m5, bot.live_m5), "M5", bot)
        self._write_diagnostics(bot)

    def _write_diagnostics(self, bot: TradingSignalBotV3) -> None:
        if not self.analysis_text:
            return
        trade_age = bot._age(bot.last_trade_rx_mono)
        kline_age = bot._age(bot.last_kline_rx_mono)
        rest_age = bot._age(bot.last_rest_ok_mono)
        live1 = bot.live_m1
        live5 = bot.live_m5
        text = (
            f"VERSION: {APP_VERSION}\n"
            f"DATABASE: {bot.database_path}\n\n"
            f"PRICE: {bot.live_price:,.2f}\n"
            f"AGGTRADE TICKS: {bot.trade_ticks:,}\n"
            f"TRADE AGE: {trade_age if trade_age is not None else -1:.3f}s\n"
            f"KLINE AGE: {kline_age if kline_age is not None else -1:.3f}s\n"
            f"REST AGE: {rest_age if rest_age is not None else -1:.3f}s\n"
            f"WS CONNECTED: {bot.ws_connected}\n"
            f"WS RECONNECTS: {bot.ws_reconnects}\n"
            f"REST FALLBACK HITS: {bot.rest_fallback_hits}\n"
            f"LAST MARKET ERROR: {bot.last_market_error or '-'}\n"
            f"TELEGRAM ERROR: {bot.telegram.last_error or '-'}\n"
            f"TELEGRAM POLL CONFLICT: {bot.telegram.poll_conflict}\n\n"
            f"M1 HISTORY: {len(bot.m1)}/1440\n"
            f"M5 HISTORY: {len(bot.m5)}/288\n"
            f"M1 LIVE: {self._candle_line(live1)}\n"
            f"M5 LIVE: {self._candle_line(live5)}\n\n"
            f"LAST DECISION: {bot.last_decision_state}\n"
        )
        self.analysis_text.configure(state="normal")
        self.analysis_text.delete("1.0", tk.END)
        self.analysis_text.insert("1.0", text)
        self.analysis_text.configure(state="disabled")

    @staticmethod
    def _candle_line(candle) -> str:
        if candle is None:
            return "NONE"
        return f"O={candle.open:.2f} H={candle.high:.2f} L={candle.low:.2f} C={candle.close:.2f} bucket={candle.open_time}"

    def _draw_candles(self, canvas: tk.Canvas | None, rows: list, interval: str, bot: TradingSignalBotV3) -> None:
        if not canvas or not canvas.winfo_exists():
            return
        canvas.delete("all")
        width = max(canvas.winfo_width(), 500)
        height = max(canvas.winfo_height(), 280)
        left, right, top, bottom = 58, 95, 62, 25
        plot_w, plot_h = width - left - right, height - top - bottom
        if not rows:
            canvas.create_text(width / 2, height / 2, text="Đang chờ Binance...", fill="#b7bdc6")
            return
        highs = [float(c.high) for c in rows]
        lows = [float(c.low) for c in rows]
        hi, lo = max(highs), min(lows)
        padding = max((hi - lo) * 0.08, max(abs(hi), 1) * 0.00002)
        hi += padding
        lo -= padding
        span = max(hi - lo, 0.01)

        def y(price: float) -> float:
            return top + (hi - price) / span * plot_h

        last = rows[-1]
        last_close = float(last.close)
        trade_age = bot._age(bot.last_trade_rx_mono)
        source = "WS" if trade_age is not None and trade_age <= 2.5 else "REST"
        canvas.create_text(left, 18, text=f"{interval} • {source} • LAST {last_close:,.2f} • TICKS {bot.trade_ticks:,}", anchor="w", fill="#f0b90b", font=("Segoe UI", 10, "bold"))
        canvas.create_text(left, 38, text="Nến cuối lấy OHLC trực tiếp từ live snapshot; refresh UI 100ms", anchor="w", fill="#848e9c", font=("Segoe UI", 8))
        for i in range(6):
            gy = top + plot_h * i / 5
            price = hi - span * i / 5
            canvas.create_line(left, gy, width - right, gy, fill="#202630")
            canvas.create_text(width - right + 5, gy, text=f"{price:,.2f}", anchor="w", fill="#848e9c")
        slot = plot_w / max(len(rows), 1)
        body_w = max(2, min(9, slot * 0.62))
        for idx, candle in enumerate(rows):
            x = left + slot * (idx + 0.5)
            color = "#0ecb81" if candle.close >= candle.open else "#f6465d"
            canvas.create_line(x, y(candle.high), x, y(candle.low), fill=color)
            y_open, y_close = y(candle.open), y(candle.close)
            if abs(y_open - y_close) < 1:
                canvas.create_line(x - body_w / 2, y_open, x + body_w / 2, y_open, fill=color, width=2)
            else:
                canvas.create_rectangle(x - body_w / 2, min(y_open, y_close), x + body_w / 2, max(y_open, y_close), fill=color, outline=color)
        last_y = y(last_close)
        canvas.create_line(left, last_y, width - right, last_y, fill="#f0b90b", dash=(5, 4))
        canvas.create_text(width - right + 5, last_y, text=f"{last_close:,.2f}", anchor="w", fill="#f0b90b")

    def exit_application_force(self) -> None:
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.engine.stop()
        try:
            self.root.destroy()
        except Exception:
            pass

    def exit_application(self) -> None:
        if not messagebox.askyesno("Thoát", "Thoát hoàn toàn sẽ dừng phân tích và gửi lệnh. Tiếp tục?"):
            return
        self.exit_application_force()

    def run(self) -> None:
        self.root.mainloop()


def send_control(port: int, command: bytes, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((CONTROL_HOST, port), timeout=timeout) as connection:
            connection.sendall(command)
        return True
    except OSError:
        return False


def shutdown_legacy_v2() -> None:
    if send_control(LEGACY_CONTROL_PORT, b"EXIT", 0.3):
        import time
        time.sleep(0.8)


def acquire_single_instance():
    if os.name != "nt":
        return None
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:
        send_control(CONTROL_PORT, b"OPEN", 1.0)
        sys.exit(0)
    return handle


if __name__ == "__main__":
    shutdown_legacy_v2()
    _mutex = acquire_single_instance()
    TrayApplication().run()
