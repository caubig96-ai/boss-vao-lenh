from __future__ import annotations

import asyncio
import logging
import signal
from collections import deque
from datetime import datetime, time as dt_time, timezone

import aiohttp

from config import Config
from database import Database
from indicators import blended_prediction, candle_analysis
from models import Candle, Prediction
from telegram_bot import TelegramBot

BINANCE_REST = "https://api.binance.com"
BINANCE_WS = "wss://stream.binance.com:9443/stream"
log = logging.getLogger("boss-vao-lenh")


class TradingSignalBot:
    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config.database_path)
        self.telegram = TelegramBot(config.telegram_token, config.telegram_chat_id, self.handle_telegram)
        self.http: aiohttp.ClientSession | None = None
        self.m1: deque[Candle] = deque(maxlen=1500)
        self.m5: deque[Candle] = deque(maxlen=1500)
        self.live_m5: Candle | None = None
        self.live_price = 0.0
        self.decision_tasks: dict[int, asyncio.Task] = {}
        self.stop_event = asyncio.Event()

    async def setup(self) -> None:
        await self.db.open()
        await self.db.set_default("manual_enabled", "1")
        await self.db.set_default("risk_pause_until", "0")
        await self.db.set_default("risk_cycle_losses", "0")
        await self.db.set_default("base_bet", str(self.config.base_bet))
        await self.db.set_default("payout_rate", str(self.config.payout_rate))
        await self.db.set_default("bet_step", "1")
        await self.db.set_default("current_balance", "0")
        await self.db.set_default("pause_started_at", "0")
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        await self.telegram.open()
        await self.backfill()
        await self.settle_pending()

    async def close(self) -> None:
        for task in self.decision_tasks.values():
            task.cancel()
        await self.telegram.close()
        if self.http:
            await self.http.close()
        await self.db.close()

    async def backfill(self) -> None:
        for interval, target in (("1m", self.m1), ("5m", self.m5)):
            params = {"symbol": self.config.symbol, "interval": interval, "limit": 1000}
            async with self.http.get(f"{BINANCE_REST}/api/v3/klines", params=params) as response:
                response.raise_for_status()
                rows = await response.json()
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            target.clear()
            for row in rows:
                candle = Candle.from_rest(interval, row)
                if candle.close_time < now_ms:
                    target.append(candle)
                    await self.db.save_candle(candle)
        log.info("Đã nạp %d nến M1 và %d nến M5", len(self.m1), len(self.m5))

    async def websocket_loop(self) -> None:
        streams = f"{self.config.symbol.lower()}@aggTrade/{self.config.symbol.lower()}@kline_1m/{self.config.symbol.lower()}@kline_5m"
        retry = 1
        while not self.stop_event.is_set():
            try:
                async with self.http.ws_connect(BINANCE_WS, params={"streams": streams}, heartbeat=20) as ws:
                    retry = 1
                    log.info("Đã kết nối Binance WebSocket")
                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            await self.handle_market_message(message.json().get("data", {}))
                        elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("WebSocket lỗi: %s; kết nối lại sau %ss", exc, retry)
                await asyncio.sleep(retry)
                retry = min(retry * 2, 30)
                try:
                    await self.backfill()
                    await self.settle_pending()
                except Exception as backfill_exc:
                    log.warning("Bù dữ liệu lỗi: %s", backfill_exc)

    async def handle_market_message(self, data: dict) -> None:
        event = data.get("e")
        if event == "aggTrade":
            self.live_price = float(data["p"])
            return
        if event != "kline":
            return
        candle = Candle.from_ws(data)
        if candle.interval == "5m":
            is_new_market = self.live_m5 is None or candle.open_time != self.live_m5.open_time
            self.live_m5 = candle
            self.live_price = candle.close
            if is_new_market:
                self.schedule_decision(candle)
        if candle.closed:
            target = self.m1 if candle.interval == "1m" else self.m5
            if not target or target[-1].open_time != candle.open_time:
                target.append(candle)
            else:
                target[-1] = candle
            await self.db.save_candle(candle)
            if candle.interval == "5m":
                await self.settle_market(candle)

    def schedule_decision(self, candle: Candle) -> None:
        if candle.open_time in self.decision_tasks:
            return
        server_now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        elapsed = (server_now_ms - candle.open_time) / 1000
        # Không phát tín hiệu muộn cho phiên hiện tại khi app vừa khởi động.
        if elapsed > 20:
            return
        delay = max(0.0, self.config.decision_second - elapsed)
        self.decision_tasks[candle.open_time] = asyncio.create_task(self.make_decision(candle, delay))

    async def make_decision(self, candle: Candle, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            if self.live_m5 is None or self.live_m5.open_time != candle.open_time:
                return
            direction, confidence, p1, p5, samples = blended_prediction(
                list(self.m1), list(self.m5), self.live_price, candle.open
            )
            # Chế độ bắt buộc: mỗi phiên hợp lệ luôn chọn UP hoặc DOWN.
            # confidence vẫn được công khai để người dùng nhận biết tín hiệu yếu.
            actual = await self.signals_enabled()
            base_bet = float(await self.db.get("base_bet", str(self.config.base_bet)))
            step = int(await self.db.get("bet_step", "1"))
            bet = min(base_bet * (2 if step == 2 else 1), self.config.max_bet)
            prediction = Prediction(candle.open_time, candle.close_time, candle.open, self.live_price,
                                    direction, confidence, p1, p5, samples, bet, step, actual)
            if not await self.db.create_signal(prediction):
                return
            if actual:
                message_id = await self.telegram.send(await self.signal_text(prediction))
                await self.db.update_message_id(candle.open_time, message_id)
        finally:
            self.decision_tasks.pop(candle.open_time, None)

    async def signals_enabled(self) -> bool:
        if await self.db.get("manual_enabled", "1") != "1":
            return False
        pause_until = int(await self.db.get("risk_pause_until", "0"))
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if pause_until > now_ms:
            return False
        if pause_until:
            await self.db.set("risk_pause_until", 0)
            await self.db.set("risk_cycle_losses", 0)
            await self.telegram.send("✅ <b>ĐÃ HẾT 30 PHÚT TẠM NGHỈ</b>\nBot bắt đầu gửi tín hiệu mới.")
        return True

    async def settle_market(self, candle: Candle) -> None:
        rows = [row for row in await self.db.pending() if int(row["market_open_time"]) == candle.open_time]
        for row in rows:
            await self.settle_row(row, candle.close)

    async def settle_pending(self) -> None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for row in await self.db.pending():
            if int(row["market_close_time"]) >= now_ms:
                continue
            params = {"symbol": self.config.symbol, "interval": "5m",
                      "startTime": int(row["market_open_time"]), "limit": 1}
            async with self.http.get(f"{BINANCE_REST}/api/v3/klines", params=params) as response:
                response.raise_for_status()
                data = await response.json()
            if data and int(data[0][0]) == int(row["market_open_time"]):
                await self.settle_row(row, float(data[0][4]))

    async def settle_row(self, row, close_price: float) -> None:
        target = float(row["target_price"])
        direction = row["direction"]
        if close_price == target:
            result = "TIE"
        else:
            result = "WIN" if (direction == "UP") == (close_price > target) else "LOSS"
        payout = float(await self.db.get("payout_rate", str(self.config.payout_rate)))
        bet = float(row["bet_amount"])
        pnl = bet * payout if result == "WIN" else (-bet if result == "LOSS" else 0.0)
        await self.db.settle(int(row["market_open_time"]), result, close_price, pnl if row["actual"] else 0.0)
        if row["actual"]:
            await self.apply_money_management(row, result, pnl)
            result_message = await self.result_text(row, close_price, result, pnl)
            if row["telegram_message_id"]:
                edited = await self.telegram.edit(int(row["telegram_message_id"]), result_message)
                if not edited:
                    await self.telegram.send(result_message)
            else:
                # Tín hiệu đã được lưu nhưng Telegram có thể lỗi đúng lúc gửi.
                # Vẫn phải báo kết quả khi phiên kết thúc để không mất lệnh.
                await self.telegram.send(result_message)

    async def apply_money_management(self, row, result: str, pnl: float) -> None:
        balance = float(await self.db.get("current_balance", "0")) + pnl
        await self.db.set("current_balance", f"{balance:.8f}")
        step = int(row["bet_step"])
        await self.db.set("bet_step", 2 if step == 1 and result == "WIN" else 1)
        cycle_losses = int(await self.db.get("risk_cycle_losses", "0"))
        cycle_losses = 0 if result == "WIN" else cycle_losses + (1 if result == "LOSS" else 0)
        await self.db.set("risk_cycle_losses", cycle_losses)
        if cycle_losses >= 2:
            until = int(datetime.now(timezone.utc).timestamp() * 1000) + 30 * 60 * 1000
            await self.db.set("risk_pause_until", until)
            await self.db.set("pause_started_at", int(datetime.now(timezone.utc).timestamp() * 1000))

    def day_start_ms(self) -> int:
        now = datetime.now(self.config.timezone)
        start = datetime.combine(now.date(), dt_time.min, tzinfo=self.config.timezone)
        return int(start.timestamp() * 1000)

    async def stats_text(self) -> str:
        virtual = await self.db.stats(self.day_start_ms(), actual_only=False)
        actual = await self.db.stats(self.day_start_ms(), actual_only=True)
        balance = float(await self.db.get("current_balance", "0"))
        actual_total = (actual["wins"] or 0) + (actual["losses"] or 0) + (actual["ties"] or 0)
        virtual_decided = (virtual["wins"] or 0) + (virtual["losses"] or 0)
        win_rate = ((virtual["wins"] or 0) / virtual_decided * 100) if virtual_decided else 0
        return (
            "\n\n📊 <b>THỐNG KÊ HÔM NAY</b>\n"
            f"🟢 Thắng: <b>{actual['wins'] or 0}</b> | 🔴 Thua: <b>{actual['losses'] or 0}</b>\n"
            f"📋 Tổng lệnh thực tế: <b>{actual_total}</b>\n"
            f"💰 Tổng tiền đã đặt: <b>{actual['staked']:.2f} USDT</b>\n"
            f"💵 Lãi/lỗ ròng: <b>{actual['pnl']:+.2f} USDT</b>\n"
            f"💳 Số dư hiện tại: <b>{balance:.2f} USDT</b>\n\n"
            "📡 <b>PHÂN TÍCH 24/7</b>\n"
            f"Thắng: {virtual['wins'] or 0} | Thua: {virtual['losses'] or 0} | Hòa: {virtual['ties'] or 0}\n"
            f"Tỷ lệ thắng: {win_rate:.1f}%"
        )

    async def signal_text(self, p: Prediction) -> str:
        local_open = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp(p.market_close_time / 1000, self.config.timezone)
        label = "🟢 𝗠𝗨𝗔 𝗧Ă𝗡𝗚" if p.direction == "UP" else "🔴 𝗠𝗨𝗔 𝗚𝗜Ả𝗠"
        quality = "CAO" if p.confidence >= 0.65 else "TRUNG BÌNH" if p.confidence >= 0.57 else "THẤP"
        history_side = "tăng" if p.direction == "UP" else "giảm"
        history_rate = p.confidence * 100
        m1_analysis = candle_analysis(list(self.m1), "M1")
        m5_analysis = candle_analysis(list(self.m5), "M5")
        return (
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{label}: {p.bet_amount:.2f} USDT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ Phiên: {local_open:%H:%M}–{local_close:%H:%M}\n"
            f"🎯 Target: <code>{p.target_price:,.2f}</code> USDT\n"
            f"💵 Giá lúc báo: <code>{p.signal_price:,.2f}</code> USDT\n"
            f"📈 Độ tin cậy: <b>{p.confidence * 100:.1f}%</b>\n"
            f"⚖️ Chất lượng tín hiệu: <b>{quality}</b>\n"
            f"🔎 M1: {p.m1_probability * 100:.1f}% tăng | M5: {p.m5_probability * 100:.1f}% tăng\n"
            f"🕯 {m1_analysis}\n"
            f"🕯 {m5_analysis}\n"
            f"🧩 Mẫu tương tự nghiêng {history_side}: <b>{history_rate:.1f}%</b> ({p.pattern_samples} mẫu)\n"
            f"🔢 Tầng tiền: <b>LỆNH {p.bet_step}</b>\n\n"
            "⏳ <b>KẾT QUẢ: ĐANG CHỜ</b>" + await self.stats_text()
        )

    async def result_text(self, row, close_price: float, result: str, pnl: float) -> str:
        local_open = datetime.fromtimestamp(row["market_open_time"] / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp(row["market_close_time"] / 1000, self.config.timezone)
        label = "🟢 𝗠𝗨𝗔 𝗧Ă𝗡𝗚" if row["direction"] == "UP" else "🔴 𝗠𝗨𝗔 𝗚𝗜Ả𝗠"
        result_label = {"WIN": "✅ ĐÃ THẮNG", "LOSS": "❌ ĐÃ THUA", "TIE": "➖ ĐÃ HÒA"}[result]
        base = float(await self.db.get("base_bet", str(self.config.base_bet)))
        next_step = int(await self.db.get("bet_step", "1"))
        next_bet = min(base * (2 if next_step == 2 else 1), self.config.max_bet)
        return (
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{label}: {float(row['bet_amount']):.2f} USDT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ Phiên: {local_open:%H:%M}–{local_close:%H:%M}\n"
            f"🎯 Target: <code>{float(row['target_price']):,.2f}</code> USDT\n"
            f"🏁 Giá đóng: <code>{close_price:,.2f}</code> USDT\n"
            f"📈 Độ tin cậy lúc báo: <b>{float(row['confidence']) * 100:.1f}%</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{result_label}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Lãi/lỗ phiên này: <b>{pnl:+.2f} USDT</b>\n"
            f"➡️ Lệnh tiếp theo: <b>{next_bet:.2f} USDT – LỆNH {next_step}</b>" + await self.stats_text()
        )

    async def handle_telegram(self, kind: str, value: str, raw: dict) -> None:
        if kind == "callback":
            if value == "stop":
                await self.db.set("manual_enabled", 0)
                await self.db.set("pause_started_at", int(datetime.now(timezone.utc).timestamp() * 1000))
                await self.telegram.send("🛑 <b>ĐÃ DỪNG GỬI LỆNH</b>\nTool vẫn phân tích và chấm kết quả 24/7.")
            elif value == "start":
                await self.db.set("manual_enabled", 1)
                await self.telegram.send("▶️ <b>ĐÃ CHẠY LẠI</b>" + await self.stats_text())
            elif value == "status":
                await self.telegram.send(await self.status_text())
            elif value == "setbet_help":
                await self.telegram.send("💵 Gửi <code>/setbet 2</code> để đặt Lệnh 1 = 2 USDT và Lệnh 2 = 4 USDT.")
            return
        parts = value.split()
        command = parts[0].lower()
        try:
            if command == "/setbet" and len(parts) == 2:
                amount = float(parts[1])
                if amount <= 0 or amount * 2 > self.config.max_bet:
                    raise ValueError
                await self.db.set("base_bet", amount)
                await self.telegram.send(f"✅ <b>ĐÃ ĐỔI VỐN</b>\nLệnh 1: {amount:.2f} USDT\nLệnh 2: {amount * 2:.2f} USDT")
            elif command == "/setbalance" and len(parts) == 2:
                amount = float(parts[1])
                await self.db.set("current_balance", amount)
                await self.telegram.send(f"✅ Số dư hiện tại: <b>{amount:.2f} USDT</b>")
            elif command == "/setpayout" and len(parts) == 2:
                rate = float(parts[1])
                rate = rate / 100 if rate > 2 else rate
                if not 0 < rate <= 2:
                    raise ValueError
                await self.db.set("payout_rate", rate)
                await self.telegram.send(f"✅ Tỷ lệ trả thưởng: <b>{rate * 100:.1f}%</b>")
            elif command in ("/status", "/start"):
                await self.telegram.send(await self.status_text())
            else:
                await self.telegram.send("Lệnh: /status, /setbet 1, /setbalance 100, /setpayout 80")
        except (ValueError, IndexError):
            await self.telegram.send("⚠️ Giá trị không hợp lệ. Ví dụ: <code>/setbet 1</code>")

    async def status_text(self) -> str:
        enabled = await self.db.get("manual_enabled", "1") == "1"
        base = float(await self.db.get("base_bet", str(self.config.base_bet)))
        step = int(await self.db.get("bet_step", "1"))
        return (
            "🤖 <b>BÁO CÁO BOT</b>\n"
            f"Trạng thái gửi lệnh: <b>{'ĐANG CHẠY' if enabled else 'ĐANG DỪNG'}</b>\n"
            f"Giá BTC: <code>{self.live_price:,.2f}</code> USDT\n"
            f"Vốn gốc: <b>{base:.2f}</b> | Tầng hiện tại: <b>LỆNH {step}</b>" + await self.stats_text()
        )

    async def run(self) -> None:
        await self.setup()
        await self.telegram.send("🤖 <b>BOT ĐÃ KHỞI ĐỘNG</b>\nĐang nhận nến Binance và phân tích 24/7.")
        tasks = [asyncio.create_task(self.websocket_loop()), asyncio.create_task(self.telegram.poll())]
        await self.stop_event.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.close()


async def async_main() -> None:
    config = Config()
    config.validate()
    logging.basicConfig(level=getattr(logging, config.log_level),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bot = TradingSignalBot(config)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, bot.stop_event.set)
    await bot.run()


if __name__ == "__main__":
    asyncio.run(async_main())
