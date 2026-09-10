from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import sqlite3
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
MUTEX_NAME = "Local\\BossVaoLenh_SingleInstance"


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
        self.status_var = tk.StringVar(value="Đang khởi động...")
        self._register_autostart()
        self._create_tray()
        if self.config.telegram_token and self.config.telegram_chat_id:
            self.engine.start()
        else:
            self.status_var.set("Cần cài Telegram lần đầu")
            self.root.after(300, self.show_first_run_setup)
        self.root.after(1500, self._check_engine)

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
        self.dashboard.title("Boss Vào Lệnh – Phân tích M1 / M5")
        self.dashboard.geometry("980x620")
        self.dashboard.minsize(820, 520)
        self.dashboard.protocol("WM_DELETE_WINDOW", self.hide_dashboard)
        header = ttk.Frame(self.dashboard, padding=12)
        header.pack(fill="x")
        ttk.Label(header, text="BOSS VÀO LỆNH", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self.status_var, font=("Segoe UI", 10)).pack(side="right")
        panels = ttk.Panedwindow(self.dashboard, orient=tk.HORIZONTAL)
        panels.pack(fill="both", expand=True, padx=12, pady=8)
        m1_frame = ttk.LabelFrame(panels, text="PHÂN TÍCH NẾN 1 PHÚT", padding=10)
        m5_frame = ttk.LabelFrame(panels, text="PHÂN TÍCH NẾN 5 PHÚT", padding=10)
        panels.add(m1_frame, weight=1)
        panels.add(m5_frame, weight=1)
        self.m1_text = tk.Text(m1_frame, font=("Consolas", 11), state="disabled", wrap="word")
        self.m5_text = tk.Text(m5_frame, font=("Consolas", 11), state="disabled", wrap="word")
        self.m1_text.pack(fill="both", expand=True)
        self.m5_text.pack(fill="both", expand=True)
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
        self.dashboard.after(2000, self._refresh_dashboard)
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
                last_signal = conn.execute("SELECT * FROM signals ORDER BY market_open_time DESC LIMIT 1").fetchone()
                settings = dict(conn.execute("SELECT key,value FROM settings").fetchall())
            self._write_text(self.m1_text, self._candle_panel(m1, None, settings))
            self._write_text(self.m5_text, self._candle_panel(m5, last_signal, settings))
        except sqlite3.Error as exc:
            self.status_var.set(f"Đang chờ dữ liệu: {exc}")

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
        self.engine.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def acquire_single_instance():
    if os.name != "nt":
        return None
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, "Boss Vào Lệnh đang chạy ở khay hệ thống.", APP_NAME, 0x40)
        sys.exit(0)
    return handle


if __name__ == "__main__":
    _mutex = acquire_single_instance()
    TrayApplication().run()
