import asyncio
import threading
import tkinter as tk
from tkinter import ttk

import runtime_v378

APP_VERSION = runtime_v378.APP_VERSION


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Boss Vào Lệnh {APP_VERSION}")
        self.geometry("560x360")
        self.resizable(True, True)
        self.status = tk.StringVar(value="Sẵn sàng")
        ttk.Label(self, text=f"Boss Vào Lệnh {APP_VERSION}", font=("Segoe UI", 18, "bold")).pack(pady=(24, 8))
        ttk.Label(self, text="Dự đoán nến M5 & Telegram", font=("Segoe UI", 11)).pack()
        ttk.Button(self, text="Khởi động", command=self.start_runtime).pack(pady=30)
        ttk.Label(self, textvariable=self.status).pack(pady=8)

    def start_runtime(self):
        self.status.set("Đang chạy...")
        def runner():
            try:
                asyncio.run(runtime_v378.run())
            except Exception as exc:
                self.after(0, lambda: self.status.set(f"Lỗi: {exc}"))
        threading.Thread(target=runner, daemon=True).start()


if __name__ == "__main__":
    App().mainloop()
