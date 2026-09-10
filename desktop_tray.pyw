from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import sqlite3
import socket
import sys
import threading
import tkinter as tk
import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

import pystray
from PIL import Image, ImageDraw


APP_NAME = "BossVaoLenh"
APP_VERSION = "1.8.1"
MUTEX_NAME = "Local\\BossVaoLenh_SingleInstance"
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 45873


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = app_directory()
os.chdir(BASE_DIR)

from dotenv import load_dotenv  # noqa: E402
from config import Config  # noqa: E402
from main import TradingSignalBot  # noqa: E402


class BackgroundBot:
    def __init__(self):
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.bot: TradingSignalBot | None = None
        self.error = ""
        self.ready = threading.Event()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, name="trading-engine", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            config = Config()
            config.validate()
            self.bot = TradingSignalBot(config)
            self.ready.set()
            self.loop.run_until_complete(self.bot.run())
        except Exception as exc:
            self.error = str(exc)
            logging.exception("Không khởi động được bot")
            self.ready.set()
        finally:
            self.loop.close()

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
        self.root.title("Boss Vào Lệnh")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_dashboard)
        self.engine = BackgroundBot()
        self.tray: pystray.Icon | None = None
        self.dashboard: tk.Toplevel | None = None
        self.m1_text: tk.Text | None = None
        self.m5_text: tk.Text | None = None
        self.m1_chart: tk.Canvas | None = None
        self.m5_chart: tk.Canvas | None = None
        self.status_var = tk.StringVar(value="Đang khởi động...")
        self._register_autostart()
        self._start_control_server()
        self._create_tray()
        if self.config.telegram_token and self.config.telegram_chat_id:
            self.engine.start()
        else:
            self.status_var.set("Cần cài Telegram lần đầu")
            self.root.after(300, self.show_first_run_setup)
        self.root.after(1500, self._check_engine)

    def _start_control_server(self) -> None:
        """Cho lần nhấp EXE tiếp theo mở lại cửa sổ của tiến trình hiện có."""
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
                            return
            except OSError as exc:
                self.root.after(0, lambda: self.status_var.set(f"Không mở được kênh điều khiển: {exc}"))

        threading.Thread(target=serve, name="local-control", daemon=True).start()

    @staticmethod
    def _telegram_api(token: str, method: str) -> dict:
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/{method}",
            headers={"User-Agent": "BossVaoLenh/1.0"},
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise ValueError(payload.get("description", "Telegram từ chối yêu cầu"))
        return payload

    @staticmethod
    def _save_env(token: str, chat_id: str) -> None:
        env_path = BASE_DIR / ".env"
        values = {}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip()
        values["TELEGRAM_BOT_TOKEN"] = token
        values["TELEGRAM_CHAT_ID"] = chat_id
        values.setdefault("APP_PASSWORD", "123")
        values.setdefault("TIMEZONE", "Asia/Ho_Chi_Minh")
        env_path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
        try:
            os.chmod(env_path, 0o600)
        except OSError:
            pass

    def show_first_run_setup(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Cài Telegram lần đầu")
        dialog.geometry("570x430")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        body = ttk.Frame(dialog, padding=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="KẾT NỐI TELEGRAM MỘT LẦN", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            body,
            text=("1. Mở Telegram, tìm @BotFather.\n"
                  "2. Gửi /newbot và làm theo hướng dẫn.\n"
                  "3. Sao chép Token BotFather cung cấp rồi dán bên dưới."),
            font=("Segoe UI", 10), justify="left",
        ).pack(anchor="w", pady=(12, 8))
        token_var = tk.StringVar()
        token_entry = ttk.Entry(body, textvariable=token_var, font=("Consolas", 11), show="•")
        token_entry.pack(fill="x", pady=5)
        status = tk.StringVar(value="Chưa kiểm tra Token")
        ttk.Label(body, textvariable=status, foreground="#374151").pack(anchor="w", pady=4)
        bot_username = tk.StringVar()
        detected_chat = tk.StringVar()

        def run_thread(task, success):
            def worker():
                try:
                    result = task()
                    self.root.after(0, lambda: success(result))
                except Exception as exc:
                    self.root.after(0, lambda: status.set(f"Lỗi: {exc}"))
            threading.Thread(target=worker, daemon=True).start()

        def check_token():
            token = token_var.get().strip()
            if not token:
                status.set("Hãy dán Token trước.")
                return
            status.set("Đang kiểm tra Token...")
            run_thread(lambda: self._telegram_api(token, "getMe"), token_ok)

        def token_ok(payload):
            username = payload["result"].get("username", "")
            bot_username.set(username)
            status.set(f"Token hợp lệ – bot @{username}. Hãy mở bot, nhấn START hoặc gửi /start.")
            detect_button.configure(state="normal")

        def detect_chat():
            token = token_var.get().strip()
            status.set("Đang tìm tin nhắn /start của anh...")
            run_thread(lambda: self._telegram_api(token, "getUpdates"), chat_ok)

        def chat_ok(payload):
            candidates = []
            for update in payload.get("result", []):
                message = update.get("message") or update.get("edited_message")
                if message and message.get("chat", {}).get("type") == "private":
                    candidates.append(message["chat"])
            if not candidates:
                status.set("Chưa thấy /start. Hãy nhắn /start cho bot rồi bấm lại.")
                return
            chat = candidates[-1]
            detected_chat.set(str(chat["id"]))
            name = chat.get("first_name") or chat.get("username") or str(chat["id"])
            status.set(f"Đã tìm thấy Telegram: {name} – Chat ID {chat['id']}")
            save_button.configure(state="normal")

        def save_and_start():
            self._save_env(token_var.get().strip(), detected_chat.get())
            load_dotenv(BASE_DIR / ".env", override=True)
            self.config = Config()
            dialog.destroy()
            self.status_var.set("Đã lưu Telegram – đang khởi động bot")
            self.engine.start()
            messagebox.showinfo("Hoàn tất", "Đã kết nối Telegram. Những lần sau tool sẽ tự chạy.")

        ttk.Button(body, text="1. KIỂM TRA TOKEN", command=check_token).pack(fill="x", pady=(10, 5))
        detect_button = ttk.Button(body, text="2. TÔI ĐÃ NHẮN /START – TỰ LẤY CHAT ID",
                                   command=detect_chat, state="disabled")
        detect_button.pack(fill="x", pady=5)
        save_button = ttk.Button(body, text="3. LƯU VÀ CHẠY TOOL", command=save_and_start, state="disabled")
        save_button.pack(fill="x", pady=5)
        ttk.Label(body, text="Token được lưu trên máy trong tệp .env và không đẩy lên GitHub.",
                  foreground="#6b7280").pack(anchor="w", pady=(12, 0))

    def _register_autostart(self) -> None:
        if os.name != "nt":
            return
        import winreg

        if getattr(sys, "frozen", False):
            command = f'"{sys.executable}"'
        else:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            command = f'"{pythonw}" "{Path(__file__).resolve()}"'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)

    @staticmethod
    def _icon_image() -> Image.Image:
        image = Image.new("RGB", (64, 64), "#111827")
        draw = ImageDraw.Draw(image)
        draw.ellipse((6, 6, 58, 58), fill="#f59e0b")
        draw.text((20, 14), "B", fill="white", stroke_width=1)
        draw.polygon([(18, 44), (29, 31), (37, 37), (50, 20), (50, 32),
                      (37, 48), (29, 41)], fill="#16a34a")
        return image

    def _create_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Mở bảng điều khiển", self._tray_open, default=True),
            pystray.MenuItem("Dừng gửi tín hiệu", self._tray_pause),
            pystray.MenuItem("Chạy gửi tín hiệu", self._tray_resume),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Thoát hoàn toàn", self._tray_exit),
        )
        self.tray = pystray.Icon(APP_NAME, self._icon_image(), "Boss Vào Lệnh", menu)
        threading.Thread(target=self.tray.run, name="tray-icon", daemon=True).start()

    def _tray_open(self, icon=None, item=None) -> None:
        self.root.after(0, self.request_password)

    def _tray_pause(self, icon=None, item=None) -> None:
        self._set_db_setting("manual_enabled", "0")
        self.root.after(0, lambda: self.status_var.set("Đang phân tích – đã dừng gửi tín hiệu"))

    def _tray_resume(self, icon=None, item=None) -> None:
        self._set_db_setting("manual_enabled", "1")
        self.root.after(0, lambda: self.status_var.set("Đang phân tích và gửi tín hiệu"))

    def _tray_exit(self, icon=None, item=None) -> None:
        self.root.after(0, self.exit_application)

    def _db_path(self) -> Path:
        path = Path(self.config.database_path)
        return path if path.is_absolute() else BASE_DIR / path

    def _set_db_setting(self, key: str, value: str) -> None:
        path = self._db_path()
        if not path.exists():
            return
        try:
            with sqlite3.connect(path, timeout=5) as conn:
                conn.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
                )
        except sqlite3.Error as exc:
            self.root.after(0, lambda: messagebox.showerror("Lỗi", str(exc)))

    def _check_engine(self) -> None:
        if not self.config.telegram_token or not self.config.telegram_chat_id:
            self.status_var.set("Cần cài Telegram lần đầu")
        elif self.engine.error:
            self.status_var.set(f"Lỗi cấu hình: {self.engine.error}")
        elif self.engine.thread and self.engine.thread.is_alive():
            self.status_var.set("Đang chạy ẩn và phân tích 24/7")
        else:
            self.status_var.set("Tiến trình phân tích đã dừng")
        self.root.after(5000, self._check_engine)

    def request_password(self) -> None:
        if not self.config.telegram_token or not self.config.telegram_chat_id:
            self.show_first_run_setup()
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Mở Boss Vào Lệnh")
        dialog.geometry("330x165")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        ttk.Label(dialog, text="NHẬP MẬT KHẨU", font=("Segoe UI", 14, "bold")).pack(pady=(18, 8))
        password = ttk.Entry(dialog, show="•", font=("Segoe UI", 13), justify="center")
        password.pack(fill="x", padx=35)
        password.focus_set()

        def submit(event=None):
            if password.get() == self.config.app_password:
                dialog.destroy()
                self.show_dashboard()
            else:
                password.delete(0, tk.END)
                messagebox.showerror("Sai mật khẩu", "Mật khẩu không đúng.", parent=dialog)

        password.bind("<Return>", submit)
        ttk.Button(dialog, text="MỞ TOOL", command=submit).pack(pady=12)

    def show_dashboard(self) -> None:
        if self.dashboard and self.dashboard.winfo_exists():
            self.dashboard.deiconify()
            self.dashboard.lift()
            return
        self.dashboard = tk.Toplevel(self.root)
        self.dashboard.title(f"Boss Vào Lệnh v{APP_VERSION} – Phân tích M1 / M5")
        self.dashboard.geometry("980x620")
        self.dashboard.minsize(820, 520)
        self.dashboard.protocol("WM_DELETE_WINDOW", self.hide_dashboard)
        header = ttk.Frame(self.dashboard, padding=12)
        header.pack(fill="x")
        ttk.Label(header, text=f"BOSS VÀO LỆNH  •  v{APP_VERSION}", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self.status_var, font=("Segoe UI", 10)).pack(side="right")
        tab_style = ttk.Style(self.dashboard)
        tab_style.configure("Boss.TNotebook.Tab", font=("Segoe UI", 11, "bold"), padding=(18, 9))
        notebook = ttk.Notebook(self.dashboard, style="Boss.TNotebook")
        notebook.pack(fill="both", expand=True, padx=12, pady=8)
        analysis_tab = ttk.Frame(notebook)
        chart_tab = ttk.Frame(notebook)
        notebook.add(analysis_tab, text="BẢNG PHÂN TÍCH")
        notebook.add(chart_tab, text="BIỂU ĐỒ NẾN BINANCE")
        notebook.select(chart_tab)
        panels = ttk.Panedwindow(analysis_tab, orient=tk.HORIZONTAL)
        panels.pack(fill="both", expand=True)
        m1_frame = ttk.LabelFrame(panels, text="PHÂN TÍCH NẾN 1 PHÚT", padding=10)
        m5_frame = ttk.LabelFrame(panels, text="PHÂN TÍCH NẾN 5 PHÚT", padding=10)
        panels.add(m1_frame, weight=1)
        panels.add(m5_frame, weight=1)
        self.m1_text = tk.Text(m1_frame, font=("Consolas", 11), state="disabled", wrap="word")
        self.m5_text = tk.Text(m5_frame, font=("Consolas", 11), state="disabled", wrap="word")
        self.m1_text.pack(fill="both", expand=True)
        self.m5_text.pack(fill="both", expand=True)
        chart_panels = ttk.Panedwindow(chart_tab, orient=tk.HORIZONTAL)
        chart_panels.pack(fill="both", expand=True)
        m1_chart_frame = ttk.LabelFrame(chart_panels, text="BTCUSDT FUTURES MAINNET – M1 LIVE", padding=0)
        m5_chart_frame = ttk.LabelFrame(chart_panels, text="BTCUSDT FUTURES MAINNET – M5 LIVE + TARGET", padding=0)
        chart_panels.add(m1_chart_frame, weight=1)
        chart_panels.add(m5_chart_frame, weight=1)
        self.m1_chart = tk.Canvas(m1_chart_frame, background="#0b0e11", highlightthickness=0)
        self.m5_chart = tk.Canvas(m5_chart_frame, background="#0b0e11", highlightthickness=0)
        self.m1_chart.pack(fill="both", expand=True)
        self.m5_chart.pack(fill="both", expand=True)
        controls = ttk.Frame(self.dashboard, padding=12)
        controls.pack(fill="x")
        ttk.Button(controls, text="DỪNG GỬI TÍN HIỆU", command=self._tray_pause).pack(side="left", padx=4)
        ttk.Button(controls, text="CHẠY GỬI TÍN HIỆU", command=self._tray_resume).pack(side="left", padx=4)
        ttk.Button(controls, text="ẨN XUỐNG TRAY", command=self.hide_dashboard).pack(side="right", padx=4)
        # Chờ Toplevel được Windows map xong rồi mới đọc và vẽ dữ liệu.
        self.dashboard.after(250, self._refresh_dashboard)

    def hide_dashboard(self) -> None:
        if self.dashboard and self.dashboard.winfo_exists():
            self.dashboard.withdraw()

    @staticmethod
    def _write_text(widget: tk.Text | None, content: str) -> None:
        if not widget or not widget.winfo_exists():
            return
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _refresh_dashboard(self) -> None:
        if not self.dashboard or not self.dashboard.winfo_exists():
            return
        # Luôn hẹn vòng tiếp theo trước. Nếu cửa sổ đang ẩn, vòng cập nhật vẫn
        # không bị mất và sẽ hoạt động ngay khi người dùng mở lại từ tray.
        self.dashboard.after(250, self._refresh_dashboard)
        if not self.dashboard.winfo_viewable():
            return
        try:
            path = self._db_path()
            if not path.exists():
                waiting = "Đang khởi động bộ máy và chờ dữ liệu Binance..."
                self._write_text(self.m1_text, waiting)
                self._write_text(self.m5_text, waiting)
                return
            with sqlite3.connect(path, timeout=3) as conn:
                conn.row_factory = sqlite3.Row
                m1 = conn.execute("SELECT * FROM candles WHERE interval='1m' ORDER BY open_time DESC LIMIT 8").fetchall()
                m5 = conn.execute("SELECT * FROM candles WHERE interval='5m' ORDER BY open_time DESC LIMIT 8").fetchall()
                m1_chart = conn.execute("SELECT * FROM candles WHERE interval='1m' ORDER BY open_time DESC LIMIT 100").fetchall()
                m5_chart = conn.execute("SELECT * FROM candles WHERE interval='5m' ORDER BY open_time DESC LIMIT 100").fetchall()
                last_signal = conn.execute("SELECT * FROM signals ORDER BY market_open_time DESC LIMIT 1").fetchone()
                settings = dict(conn.execute("SELECT key,value FROM settings").fetchall())
            self._write_text(self.m1_text, self._candle_panel(m1, None, settings))
            self._write_text(self.m5_text, self._candle_panel(m5, last_signal, settings))
            bot = self.engine.bot
            m1_plot = self._with_live(list(reversed(m1_chart)), bot.live_m1 if bot else None)
            m5_plot = self._with_live(list(reversed(m5_chart)), bot.live_m5 if bot else None)
            live_price = float(bot.live_price) if bot and bot.live_price else None
            self._draw_candles(self.m1_chart, m1_plot, "M1", live_price=live_price)
            target = float(last_signal["target_price"]) if last_signal else None
            self._draw_candles(self.m5_chart, m5_plot, "M5", target, live_price)
        except sqlite3.Error as exc:
            self.status_var.set(f"Đang chờ dữ liệu: {exc}")

    @staticmethod
    def _with_live(rows: list, live) -> list:
        if live is None:
            return rows
        if rows and int(rows[-1]["open_time"]) == live.open_time:
            rows = rows[:-1]
        return (rows + [live])[-100:]

    @staticmethod
    def _value(row, key: str):
        return getattr(row, key) if hasattr(row, key) else row[key]

    def _draw_candles(self, canvas: tk.Canvas | None, rows: list, interval: str,
                      target: float | None = None, live_price: float | None = None) -> None:
        if not canvas or not canvas.winfo_exists():
            return
        canvas.delete("all")
        width = max(canvas.winfo_width(), 420)
        height = max(canvas.winfo_height(), 300)
        left, right, top, bottom = 58, 90, 70, 28
        plot_width, plot_height = width - left - right, height - top - bottom
        if not rows:
            canvas.create_text(width / 2, height / 2, text="Đang chờ nến Binance...", fill="#b7bdc6")
            return
        highs = [float(self._value(row, "high")) for row in rows]
        lows = [float(self._value(row, "low")) for row in rows]
        if live_price is not None:
            highs.append(live_price)
            lows.append(live_price)
        price_high, price_low = max(highs), min(lows)
        padding = max((price_high - price_low) * 0.08, price_high * 0.00002)
        price_high, price_low = price_high + padding, price_low - padding
        span = max(price_high - price_low, 0.01)

        def y(price: float) -> float:
            return top + (price_high - price) / span * plot_height

        last_close = live_price if live_price is not None else float(self._value(rows[-1], "close"))
        canvas.create_rectangle(7, 7, 176, 34, fill="#181a20", outline="#665814")
        canvas.create_text(15, 20, text="FUTURES MAINNET LIVE", anchor="w", fill="#f0b90b",
                           font=("Segoe UI", 9, "bold"))
        canvas.create_rectangle(184, 7, 252, 34, fill="#181a20", outline="#2b3139")
        canvas.create_text(192, 20, text=f"{len(rows)}/100", anchor="w", fill="#eaecef",
                           font=("Segoe UI", 9, "bold"))
        canvas.create_rectangle(260, 7, 430, 34, fill="#181a20", outline="#665814")
        canvas.create_text(268, 20, text=f"LAST {last_close:,.2f}", anchor="w", fill="#f0b90b",
                           font=("Segoe UI", 9, "bold"))
        canvas.create_text(left, 50, text=f"BTCUSDT PERPETUAL • {interval} • KLINE + AGGTRADE",
                           anchor="w", fill="#848e9c", font=("Segoe UI", 8, "bold"))
        for index in range(6):
            grid_y = top + plot_height * index / 5
            price = price_high - span * index / 5
            canvas.create_line(left, grid_y, width - right, grid_y, fill="#202630")
            canvas.create_text(width - right + 6, grid_y, text=f"{price:,.2f}", anchor="w", fill="#848e9c")
        slot = plot_width / max(len(rows), 1)
        body_width = max(2, min(9, slot * 0.62))
        for index, row in enumerate(rows):
            open_price = float(self._value(row, "open"))
            high = float(self._value(row, "high"))
            low = float(self._value(row, "low"))
            close = float(self._value(row, "close"))
            x = left + slot * (index + 0.5)
            color = "#0ecb81" if close >= open_price else "#f6465d"
            canvas.create_line(x, y(high), x, y(low), fill=color)
            y_open, y_close = y(open_price), y(close)
            if abs(y_open - y_close) < 1:
                canvas.create_line(x - body_width / 2, y_open, x + body_width / 2, y_open, fill=color, width=2)
            else:
                canvas.create_rectangle(x - body_width / 2, min(y_open, y_close),
                                        x + body_width / 2, max(y_open, y_close), fill=color, outline=color)
        if target is not None and price_low <= target <= price_high:
            target_y = y(target)
            canvas.create_line(left, target_y, width - right, target_y, fill="#f0b90b", dash=(6, 4), width=2)
            canvas.create_text(width - right + 6, target_y, text="TARGET", anchor="w", fill="#f0b90b")
        last_y = y(last_close)
        canvas.create_line(left, last_y, width - right, last_y, fill="#f0b90b", dash=(5, 4))
        canvas.create_text(width - right + 6, last_y, text=f"{last_close:,.2f}", anchor="w", fill="#f0b90b")
        first_time = datetime.fromtimestamp(int(self._value(rows[0], "open_time")) / 1000, self.config.timezone)
        last_time = datetime.fromtimestamp(int(self._value(rows[-1], "open_time")) / 1000, self.config.timezone)
        canvas.create_text(left, height - 15, text=f"{first_time:%H:%M}", anchor="w", fill="#848e9c")
        canvas.create_text(width - right, height - 15, text=f"{last_time:%H:%M}", anchor="e", fill="#848e9c")

    def _candle_panel(self, rows, signal_row, settings: dict) -> str:
        lines = []
        for row in reversed(rows):
            stamp = datetime.fromtimestamp(row["open_time"] / 1000, self.config.timezone)
            arrow = "▲" if row["close"] > row["open"] else "▼" if row["close"] < row["open"] else "–"
            lines.append(f"{stamp:%H:%M} {arrow} O {row['open']:,.2f}  C {row['close']:,.2f}\n"
                         f"       H {row['high']:,.2f}  L {row['low']:,.2f}  V {row['volume']:,.2f}")
        if signal_row:
            lines.extend([
                "\n" + "─" * 38,
                f"TÍN HIỆU: {'MUA TĂNG' if signal_row['direction'] == 'UP' else 'MUA GIẢM'}",
                f"ĐỘ TIN CẬY: {signal_row['confidence'] * 100:.1f}%",
                f"TARGET: {signal_row['target_price']:,.2f}",
                f"TRẠNG THÁI: {signal_row['result'] or 'ĐANG CHỜ'}",
                f"LỆNH: {signal_row['bet_amount']:.2f} USDT",
            ])
        enabled = settings.get("manual_enabled", "1") == "1"
        lines.extend(["\n" + "─" * 38,
                      f"GỬI TELEGRAM: {'ĐANG BẬT' if enabled else 'ĐANG DỪNG'}",
                      f"SỐ DƯ: {float(settings.get('current_balance', 0)):.2f} USDT"])
        return "\n".join(lines) if lines else "Đang chờ dữ liệu Binance..."

    def exit_application(self) -> None:
        if not messagebox.askyesno("Thoát", "Thoát hoàn toàn sẽ dừng phân tích 24/7. Tiếp tục?"):
            return
        if self.tray:
            self.tray.stop()
        try:
            with socket.create_connection((CONTROL_HOST, CONTROL_PORT), timeout=1) as connection:
                connection.sendall(b"EXIT")
        except OSError:
            pass
        self.engine.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def acquire_single_instance():
    if os.name != "nt":
        return None
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:
        try:
            with socket.create_connection((CONTROL_HOST, CONTROL_PORT), timeout=2) as connection:
                connection.sendall(b"OPEN")
        except OSError:
            ctypes.windll.user32.MessageBoxW(
                None,
                "Tool đang chạy nhưng chưa thể mở cửa sổ. Hãy kết thúc BossVaoLenh trong Task Manager rồi mở lại.",
                APP_NAME,
                0x30,
            )
        sys.exit(0)
    return handle


if __name__ == "__main__":
    _mutex = acquire_single_instance()
    TrayApplication().run()
