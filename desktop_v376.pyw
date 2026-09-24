from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import pystray
from PIL import Image, ImageDraw

from config import Config
from runtime_v4 import APP_VERSION, GREEN, RED, PatternSignalBot

APP_NAME = "BossVaoLenh"
BG = "#101317"
PANEL = "#171c22"
BORDER = "#28303a"
TEXT = "#f3f5f7"
MUTED = "#9ca8b5"
GREEN_UI = "#00b86b"
RED_UI = "#ff3b3b"
BLUE_UI = "#4aa3ff"

log = logging.getLogger("boss-vao-lenh-desktop-v4")


def persistent_root() -> Path:
    root = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
    return Path(root) / "BossVaoLenh"


def configure_logging(level_name: str) -> None:
    log_dir = persistent_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "boss-v4.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        handlers=[handler],
        force=True,
    )


def acquire_single_instance():
    if os.name != "nt":
        return None
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "BossVaoLenhV4PatternMutex")
    if ctypes.windll.kernel32.GetLastError() == 183:
        raise RuntimeError("Boss Vào Lệnh đang chạy. Hãy mở từ icon dưới system tray.")
    return handle


class BossPatternApplication:
    def __init__(self):
        self.config = Config()
        self.config.validate()
        configure_logging(self.config.log_level)

        self.root = tk.Tk()
        self.root.title(f"Boss Vào Lệnh V{APP_VERSION}")
        self.root.geometry("900x820")
        self.root.minsize(860, 760)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self.engine = PatternSignalBot(self.config)
        self.engine_thread = threading.Thread(target=self._engine_main, name="boss-v4-engine", daemon=True)
        self.engine_thread.start()

        self.tray: pystray.Icon | None = None
        self.tray_thread: threading.Thread | None = None
        self.exiting = False
        self.unlocked = False
        self.fields_loaded = False
        self.save_in_progress = False

        self.bet1_var = tk.StringVar(value="1")
        self.bet2_var = tk.StringVar(value="2")
        self.start_balance_var = tk.StringVar(value="0")
        self.payout_var = tk.StringVar(value="80")
        self.telegram_var = tk.BooleanVar(value=True)
        self.save_status_var = tk.StringVar(value="")

        self._build_ui()
        self.root.withdraw()
        self.root.after(300, self._refresh_ui)
        self.root.after(800, self._ensure_tray)

    def _engine_main(self) -> None:
        try:
            asyncio.run(self.engine.run())
        except Exception:
            log.exception("Engine V4 stopped")

    def _icon_image(self) -> Image.Image:
        image = Image.new("RGB", (64, 64), BG)
        draw = ImageDraw.Draw(image)
        draw.ellipse((7, 7, 29, 29), fill=GREEN_UI)
        draw.ellipse((35, 7, 57, 29), fill=RED_UI)
        draw.ellipse((7, 35, 29, 57), fill=RED_UI)
        draw.ellipse((35, 35, 57, 57), fill=GREEN_UI)
        return image

    def _ensure_tray(self) -> None:
        if self.exiting:
            return
        if self.tray_thread is None or not self.tray_thread.is_alive():
            menu = pystray.Menu(
                pystray.MenuItem(f"Mở Boss V{APP_VERSION}", self._tray_open, default=True),
                pystray.MenuItem("Ẩn cửa sổ", self._tray_hide),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Thoát hoàn toàn", self._tray_exit),
            )
            self.tray = pystray.Icon(APP_NAME, self._icon_image(), f"Boss Vào Lệnh V{APP_VERSION}", menu)
            self.tray_thread = threading.Thread(target=self._run_tray, name="boss-v4-tray", daemon=True)
            self.tray_thread.start()
        self.root.after(3000, self._ensure_tray)

    def _run_tray(self) -> None:
        try:
            if self.tray:
                self.tray.run()
        except Exception:
            log.exception("System tray stopped")

    def _tray_open(self, *_args) -> None:
        self.root.after(0, self.open_window)

    def _tray_hide(self, *_args) -> None:
        self.root.after(0, self.hide_window)

    def _tray_exit(self, *_args) -> None:
        self.root.after(0, self.exit_application)

    def open_window(self) -> None:
        if not self.unlocked:
            password = simpledialog.askstring(
                "Boss Vào Lệnh",
                "Nhập mật khẩu để mở bảng điều khiển:",
                show="*",
                parent=self.root,
            )
            if password is None:
                return
            if password != self.config.app_password:
                messagebox.showerror("Sai mật khẩu", "Mật khẩu không đúng.", parent=self.root)
                return
            self.unlocked = True
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self) -> None:
        self.root.withdraw()

    def _section(self, parent, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        tk.Label(
            outer, text=title, bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold"), anchor="w"
        ).pack(fill="x", padx=14, pady=(11, 7))
        return outer

    def _build_ui(self) -> None:
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, padx=18, pady=16)

        header = tk.Frame(container, bg=BG)
        header.pack(fill="x", pady=(0, 12))
        tk.Label(
            header,
            text=f"BOSS VÀO LỆNH V{APP_VERSION}",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 20, "bold"),
        ).pack(side="left")
        tk.Label(
            header,
            text="5 NẾN • chỉ một bảng nhận dạng",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(side="left", padx=14, pady=(8, 0))
        self.connection_label = tk.Label(
            header, text="● Đang khởi động", bg=BG, fg=MUTED, font=("Segoe UI", 10, "bold")
        )
        self.connection_label.pack(side="right", pady=(8, 0))

        signal = self._section(container, "4 nến trước + nến live M5 vừa kết thúc → lệnh nến kế tiếp")
        signal.pack(fill="x", pady=(0, 12))
        body = tk.Frame(signal, bg=PANEL)
        body.pack(fill="x", padx=14, pady=(0, 14))

        candles = tk.Frame(body, bg=PANEL)
        candles.pack(side="left", padx=(4, 30))
        self.candle_labels: list[tk.Label] = []
        for _ in range(5):
            label = tk.Label(
                candles, text="●", bg=PANEL, fg="#59636f",
                font=("Segoe UI Symbol", 34, "bold")
            )
            label.pack(side="left", padx=5)
            self.candle_labels.append(label)

        signal_right = tk.Frame(body, bg=PANEL)
        signal_right.pack(side="left", fill="x", expand=True)
        self.recommendation_label = tk.Label(
            signal_right, text="CHỜ MẪU", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 21, "bold"), anchor="w"
        )
        self.recommendation_label.pack(fill="x")
        self.pattern_label = tk.Label(
            signal_right, text="Mẫu: -----", bg=PANEL, fg=MUTED,
            font=("Consolas", 11), anchor="w"
        )
        self.pattern_label.pack(fill="x", pady=(4, 0))
        self.frame_label = tk.Label(
            signal_right, text="Khung: --:--–--:--", bg=PANEL, fg=TEXT,
            font=("Segoe UI", 11), anchor="w"
        )
        self.frame_label.pack(fill="x", pady=(4, 0))
        self.bet_label = tk.Label(
            signal_right, text="Lệnh kế tiếp: --", bg=PANEL, fg=BLUE_UI,
            font=("Segoe UI", 11, "bold"), anchor="w"
        )
        self.bet_label.pack(fill="x", pady=(4, 0))

        middle = tk.Frame(container, bg=BG)
        middle.pack(fill="x", pady=(0, 12))
        settings = self._section(middle, "Cài đặt tiền lệnh")
        settings.pack(side="left", fill="both", expand=True, padx=(0, 6))
        daily = self._section(middle, "Lãi / lỗ trong ngày")
        daily.pack(side="left", fill="both", expand=True, padx=(6, 0))

        form = tk.Frame(settings, bg=PANEL)
        form.pack(fill="x", padx=14, pady=(0, 12))
        self._field(form, 0, "Lệnh 1 (USDT)", self.bet1_var)
        self._field(form, 1, "Lệnh 2 (USDT)", self.bet2_var)
        self._field(form, 2, "Vốn đầu ngày (USDT)", self.start_balance_var)
        self._field(form, 3, "Trả thưởng (%)", self.payout_var)
        check = tk.Checkbutton(
            form,
            text="Gửi lệnh qua Telegram",
            variable=self.telegram_var,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=BG,
            font=("Segoe UI", 10),
        )
        check.grid(row=4, column=0, columnspan=2, sticky="w", pady=(9, 5))
        tk.Button(
            form,
            text="LƯU CÀI ĐẶT",
            command=self.save_settings,
            bg=BLUE_UI,
            fg="white",
            activebackground="#2f8be8",
            activeforeground="white",
            relief="flat",
            padx=16,
            pady=7,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(5, 3))
        tk.Label(
            form, textvariable=self.save_status_var, bg=PANEL, fg=MUTED,
            font=("Segoe UI", 9), anchor="w"
        ).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        daily_body = tk.Frame(daily, bg=PANEL)
        daily_body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.day_label = self._stat_line(daily_body, "Ngày", "--")
        self.start_label = self._stat_line(daily_body, "Vốn đầu ngày", "0.00 USDT")
        self.pnl_label = self._stat_line(daily_body, "Lãi/lỗ", "0.00 USDT", bold=True)
        self.end_label = self._stat_line(daily_body, "Số dư cuối ngày", "0.00 USDT", bold=True)
        self.wl_label = self._stat_line(daily_body, "Thắng / thua", "0 / 0")
        ttk.Separator(daily_body, orient="horizontal").pack(fill="x", pady=8)
        self.previous_label = tk.Label(
            daily_body,
            text="Ngày trước: chưa có dữ liệu",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            font=("Segoe UI", 9),
        )
        self.previous_label.pack(fill="x")

        history = self._section(container, "100 lệnh thắng / thua gần nhất  •  V = thắng  •  X = thua")
        history.pack(fill="both", expand=True)
        grid = tk.Frame(history, bg=PANEL)
        grid.pack(fill="x", padx=14, pady=(0, 8))
        self.history_cells: list[tk.Label] = []
        for row in range(10):
            grid.grid_rowconfigure(row, weight=1)
            for col in range(10):
                grid.grid_columnconfigure(col, weight=1)
                cell = tk.Label(
                    grid,
                    text="·",
                    width=3,
                    height=1,
                    bg=BG,
                    fg="#59636f",
                    font=("Consolas", 10, "bold"),
                    relief="flat",
                    padx=3,
                    pady=3,
                )
                cell.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")
                self.history_cells.append(cell)

        self.detail_label = tk.Label(
            history,
            text="Chưa có lệnh đã chốt.",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            font=("Consolas", 9),
        )
        self.detail_label.pack(fill="x", padx=14, pady=(2, 12))

        footer = tk.Label(
            container,
            text="Nguồn nến: Binance Futures M5. Nến live vừa kết thúc là nến thứ 5; kết quả gửi trước, lệnh mới gửi ngay sau khi khớp mẫu.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        )
        footer.pack(fill="x", pady=(9, 0))

    def _field(self, parent: tk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        tk.Label(
            parent, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 9), anchor="w"
        ).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        entry = tk.Entry(
            parent,
            textvariable=variable,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            justify="right",
            font=("Segoe UI", 10),
            width=14,
        )
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        parent.grid_columnconfigure(1, weight=1)

    def _stat_line(self, parent: tk.Frame, name: str, value: str, bold: bool = False) -> tk.Label:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=name, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        label = tk.Label(
            row,
            text=value,
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 10, "bold" if bold else "normal"),
        )
        label.pack(side="right")
        return label

    def save_settings(self) -> None:
        if self.save_in_progress:
            return
        try:
            bet1 = float(self.bet1_var.get().replace(",", "."))
            bet2 = float(self.bet2_var.get().replace(",", "."))
            start = float(self.start_balance_var.get().replace(",", "."))
            payout = float(self.payout_var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Sai dữ liệu", "Các ô tiền và phần trăm phải là số.", parent=self.root)
            return
        if not self.engine.loop:
            messagebox.showwarning("Chưa sẵn sàng", "Engine đang khởi động, thử lại sau vài giây.", parent=self.root)
            return

        self.save_in_progress = True
        self.save_status_var.set("Đang lưu...")
        future = asyncio.run_coroutine_threadsafe(
            self.engine.update_settings(
                bet1=bet1,
                bet2=bet2,
                start_balance=start,
                payout_percent=payout,
                telegram_enabled=bool(self.telegram_var.get()),
            ),
            self.engine.loop,
        )

        def done_callback(done):
            try:
                done.result()
                self.root.after(0, lambda: self._save_done("Đã lưu cài đặt."))
            except Exception as exc:
                self.root.after(0, lambda: self._save_failed(str(exc)))

        future.add_done_callback(done_callback)

    def _save_done(self, text: str) -> None:
        self.save_in_progress = False
        self.save_status_var.set(text)

    def _save_failed(self, error: str) -> None:
        self.save_in_progress = False
        self.save_status_var.set("Lưu thất bại")
        messagebox.showerror("Không lưu được", error, parent=self.root)

    @staticmethod
    def _fmt_money(value: float) -> str:
        return f"{float(value):,.2f} USDT"

    def _refresh_ui(self) -> None:
        if self.exiting:
            return
        snap = self.engine.snapshot()

        connected = bool(snap.get("connected"))
        self.connection_label.config(
            text="● Đang chạy" if connected else "● Đang kết nối lại",
            fg=GREEN_UI if connected else RED_UI,
        )

        colors = snap.get("colors", [])
        for idx, label in enumerate(self.candle_labels):
            value = colors[idx] if idx < len(colors) else None
            if value == GREEN:
                label.config(fg=GREEN_UI)
            elif value == RED:
                label.config(fg=RED_UI)
            else:
                label.config(fg="#59636f")

        recommendation = snap.get("recommendation")
        if recommendation == GREEN:
            self.recommendation_label.config(text="MUA XANH", fg=GREEN_UI)
        elif recommendation == RED:
            self.recommendation_label.config(text="MUA ĐỎ", fg=RED_UI)
        else:
            self.recommendation_label.config(text="KHÔNG KHỚP MẪU", fg=MUTED)
        self.pattern_label.config(text=f"Mẫu: {snap.get('pattern', '-----')}")
        self.frame_label.config(text=f"Khung: {snap.get('frame', '--:--–--:--')}")
        self.bet_label.config(
            text=f"Lệnh kế tiếp: Lệnh {int(snap.get('current_step', 1))} • "
                 f"{self._fmt_money(float(snap.get('next_bet', 0)))}"
        )

        if not self.fields_loaded and snap.get("day"):
            self.bet1_var.set(f"{float(snap.get('bet1', 1)):.2f}")
            self.bet2_var.set(f"{float(snap.get('bet2', 2)):.2f}")
            self.start_balance_var.set(f"{float(snap.get('start_balance', 0)):.2f}")
            self.payout_var.set(f"{float(snap.get('payout_percent', 80)):.2f}")
            self.telegram_var.set(bool(snap.get("telegram_enabled", True)))
            self.fields_loaded = True

        self.day_label.config(text=str(snap.get("day") or "--"))
        self.start_label.config(text=self._fmt_money(float(snap.get("start_balance", 0))))
        pnl = float(snap.get("daily_pnl", 0))
        self.pnl_label.config(
            text=self._fmt_money(pnl),
            fg=GREEN_UI if pnl > 0 else (RED_UI if pnl < 0 else TEXT)
        )
        self.end_label.config(text=self._fmt_money(float(snap.get("end_balance", 0))))
        self.wl_label.config(text=f"{int(snap.get('wins', 0))} / {int(snap.get('losses', 0))}")

        previous = snap.get("previous_day")
        if previous:
            previous_pnl = float(previous.get("pnl", 0))
            self.previous_label.config(
                text=(
                    f"Ngày trước {previous.get('day')}: "
                    f"{self._fmt_money(previous_pnl)} • cuối ngày "
                    f"{self._fmt_money(float(previous.get('end_balance', 0)))} • "
                    f"V {int(previous.get('wins', 0))} / X {int(previous.get('losses', 0))}"
                ),
                fg=GREEN_UI if previous_pnl > 0 else (RED_UI if previous_pnl < 0 else MUTED),
            )
        else:
            self.previous_label.config(text="Ngày trước: chưa có dữ liệu", fg=MUTED)

        marks = list(snap.get("history", []))[-100:]
        start_index = max(0, 100 - len(marks))
        for i, cell in enumerate(self.history_cells):
            mark_index = i - start_index
            if 0 <= mark_index < len(marks):
                mark = marks[mark_index]
                if mark == "V":
                    cell.config(text="V", bg="#0e3928", fg="#37e894")
                else:
                    cell.config(text="X", bg="#442020", fg="#ff7272")
            else:
                cell.config(text="·", bg=BG, fg="#59636f")

        details = list(snap.get("history_details", []))[-8:]
        if details:
            lines = []
            for item in reversed(details):
                icon = "V" if item["mark"] == "V" else "X"
                side = "XANH" if item["direction"] == GREEN else "ĐỎ"
                lines.append(
                    f"{item['time']}  {icon}  mua {side:<4}  "
                    f"L{item['bet_step']} {item['bet_amount']:.2f}  P/L {item['pnl']:+.2f}"
                )
            self.detail_label.config(text="\n".join(lines))
        else:
            self.detail_label.config(text="Chưa có lệnh đã chốt.")

        if snap.get("error"):
            self.save_status_var.set(str(snap.get("error")))
        self.root.after(700, self._refresh_ui)

    def exit_application(self) -> None:
        if self.exiting:
            return
        self.exiting = True
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        if self.engine.loop:
            try:
                self.engine.loop.call_soon_threadsafe(self.engine.stop_event.set)
            except Exception:
                pass
        self.root.after(200, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    mutex = None
    try:
        mutex = acquire_single_instance()
        app = BossPatternApplication()
        app.run()
    except Exception as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(f"Boss Vào Lệnh V{APP_VERSION}", f"{type(exc).__name__}: {exc}")
            root.destroy()
        finally:
            raise
    finally:
        _ = mutex


if __name__ == "__main__":
    main()
