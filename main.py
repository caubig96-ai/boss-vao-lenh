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

BINANCE_REST = "https://fapi.binance.com"
BINANCE_WS = "wss://fstream.binance.com/stream"
M1_24H = 24 * 60
M5_24H = 24 * 60 // 5
log = logging.getLogger("boss-vao-lenh")


class TradingSignalBot:
    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config.database_path)
        self.telegram = TelegramBot(config.telegram_token, config.telegram_chat_id, self.handle_telegram)
        self.http: aiohttp.ClientSession | None = None
        # Bộ nhớ live chỉ giữ đúng 24 giờ: 1440 nến M1 và 288 nến M5.
        self.m1: deque[Candle] = deque(maxlen=M1_24H)
        self.m5: deque[Candle] = deque(maxlen=M5_24H)
        self.live_m1: Candle | None = None
        self.live_m5: Candle | None = None
        self.live_price = 0.0
        self.last_market_event_ms = 0
        self.last_trade_event_ms = 0
        self.last_trade_time_ms = 0
        self.trade_ticks = 0
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
        await self.db.set_default("awaiting_setbet", "0")
        await self.db.set_default("stats_reset_at", "0")
        self.telegram.enabled = await self.db.get("manual_enabled", "1") == "1"
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

    async def _recent_closed_klines(self, interval: str, count: int) -> list[list]:
        """Nạp đủ số nến đóng gần nhất, kể cả M1 cần hơn giới hạn 1000/request."""
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        end_time = now_ms - 1
        result: list[list] = []
        while len(result) < count:
            remaining = count - len(result)
            params = {
                "symbol": self.config.symbol,
                "interval": interval,
                "limit": min(1000, remaining),
                "endTime": end_time,
            }
            async with self.http.get(f"{BINANCE_REST}/fapi/v1/klines", params=params) as response:
                response.raise_for_status()
                rows = await response.json()
            closed_rows = [row for row in rows if int(row[6]) < now_ms]
            if not closed_rows:
                break
            result = closed_rows + result
            oldest_open = int(closed_rows[0][0])
            if oldest_open <= 0:
                break
            end_time = oldest_open - 1
            if len(rows) < int(params["limit"]):
                break
        return result[-count:]

    async def backfill(self) -> None:
        for interval, target, count in (("1m", self.m1, M1_24H), ("5m", self.m5, M5_24H)):
            rows = await self._recent_closed_klines(interval, count)
            target.clear()
            for row in rows:
                candle = Candle.from_rest(interval, row)
                target.append(candle)
                await self.db.save_candle(candle)
        log.info("Đã nạp rolling 24h: %d nến M1 và %d nến M5", len(self.m1), len(self.m5))

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
                            payload = message.json()
                            await self.handle_market_message(payload.get("data", {}))
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

    def _apply_trade_to_live(self, interval: str, trade_time_ms: int, price: float) -> None:
        """Mỗi aggTrade tạo snapshot nến mới để UI luôn thấy OHLC nhất quán theo từng tick."""
        attr = "live_m1" if interval == "1m" else "live_m5"
        current: Candle | None = getattr(self, attr)
        bucket = Candle.bucket_open_time(interval, trade_time_ms)

        # Bỏ tick đến muộn thuộc một bucket đã qua để biểu đồ không giật lùi.
        if current is not None and bucket < current.open_time:
            return
        if current is None or bucket > current.open_time:
            updated = Candle.from_trade(interval, trade_time_ms, price)
        elif current.closed:
            # Kline đóng chính thức đã đến; không mở lại chính bucket đó vì một tick trễ.
            return
        else:
            updated = current.with_trade(price)
        setattr(self, attr, updated)

    def _merge_live_kline(self, candle: Candle, event_time_ms: int) -> Candle:
        """Ưu tiên OHLC chính thức, nhưng không để kline chậm ghi đè một aggTrade mới hơn."""
        attr = "live_m1" if candle.interval == "1m" else "live_m5"
        current: Candle | None = getattr(self, attr)
        if candle.closed or current is None or current.open_time != candle.open_time:
            return candle
        if self.last_trade_event_ms <= event_time_ms:
            return candle
        # Trade mới hơn event kline: giữ open/volume chính thức, giữ close/high/low mới nhất từ tick.
        return Candle(
            candle.interval,
            candle.open_time,
            candle.close_time,
            candle.open,
            max(candle.high, current.high),
            min(candle.low, current.low),
            current.close,
            candle.volume,
            False,
        )

    async def handle_market_message(self, data: dict) -> None:
        event_time_ms = int(data.get("E") or datetime.now(timezone.utc).timestamp() * 1000)
        self.last_market_event_ms = max(self.last_market_event_ms, event_time_ms)
        event = data.get("e")

        if event == "aggTrade":
            trade_time_ms = int(data.get("T") or event_time_ms)
            # Combined stream có thể giao thông báo lệch thứ tự rất nhỏ; không cho giá live quay ngược thời gian.
            if trade_time_ms < self.last_trade_time_ms:
                return
            price = float(data["p"])
            self.last_trade_time_ms = trade_time_ms
            self.last_trade_event_ms = max(self.last_trade_event_ms, event_time_ms)
            self.trade_ticks += 1
            self.live_price = price
            self._apply_trade_to_live("1m", trade_time_ms, price)
            self._apply_trade_to_live("5m", trade_time_ms, price)
            return

        if event != "kline":
            return

        raw_candle = Candle.from_ws(data)
        attr = "live_m1" if raw_candle.interval == "1m" else "live_m5"
        current: Candle | None = getattr(self, attr)

        # Nếu một tick của bucket mới đã tới trước kline đóng của bucket cũ, không kéo UI quay lại nến cũ.
        if current is None or raw_candle.open_time >= current.open_time:
            live_candle = self._merge_live_kline(raw_candle, event_time_ms)
            setattr(self, attr, live_candle)
        else:
            live_candle = current

        # Kline có thể làm nguồn dự phòng nếu aggTrade chưa tới hoặc không mới hơn bucket này.
        if self.live_price == 0.0 or (
            self.last_trade_time_ms <= raw_candle.close_time and event_time_ms >= self.last_trade_event_ms
        ):
            self.live_price = raw_candle.close

        if raw_candle.interval == "5m":
            # Gọi ở mọi kline M5; schedule_decision tự chống trùng và chỉ nhận 20 giây đầu phiên.
            self.schedule_decision(raw_candle, event_time_ms)

        if raw_candle.closed:
            target = self.m1 if raw_candle.interval == "1m" else self.m5
            if not target or target[-1].open_time < raw_candle.open_time:
                target.append(raw_candle)
            elif target[-1].open_time == raw_candle.open_time:
                target[-1] = raw_candle
            else:
                # Trường hợp hiếm event đóng đến lệch thứ tự: thay đúng phần tử thay vì append sai timeline.
                for index in range(len(target) - 1, -1, -1):
                    if target[index].open_time == raw_candle.open_time:
                        target[index] = raw_candle
                        break
            await self.db.save_candle(raw_candle)
            if raw_candle.interval == "5m":
                await self.settle_market(raw_candle)

    @staticmethod
    def decision_delay(open_time_ms: int, event_time_ms: int, decision_second: int) -> float | None:
        """Tính lịch bằng đồng hồ Binance, không phụ thuộc giờ Windows."""
        elapsed = max(0.0, (event_time_ms - open_time_ms) / 1000)
        if elapsed > 20:
            return None
        return max(0.0, decision_second - elapsed)

    def schedule_decision(self, candle: Candle, event_time_ms: int) -> None:
        if candle.open_time in self.decision_tasks:
            return
        delay = self.decision_delay(candle.open_time, event_time_ms, self.config.decision_second)
        if delay is None:
            return
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
                message_id = await self.telegram.send(await self.signal_text(prediction), enabled=True)
                await self.db.update_message_id(candle.open_time, message_id)
            await self.db.event("DECISION_CREATED", {
                "open_time": candle.open_time,
                "direction": direction,
                "actual": actual,
                "confidence": confidence,
            })
        except Exception as exc:
            log.exception("Không tạo/gửi được tín hiệu phiên %s", candle.open_time)
            try:
                await self.db.event("DECISION_ERROR", {"open_time": candle.open_time, "error": str(exc)})
            except Exception:
                pass
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
            async with self.http.get(f"{BINANCE_REST}/fapi/v1/klines", params=params) as response:
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
            # Gửi tin mới để Telegram phát thông báo ngay khi phiên M5 đóng.
            # Không chỉ sửa tin cũ vì tin bị sửa thường không tạo thông báo.
            await self.telegram.send(result_message, keyboard=False)

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
        reset_at = int(await self.db.get("stats_reset_at", "0"))
        persistent_start = max(0, reset_at)
        today_start = max(self.day_start_ms(), persistent_start)
        actual = await self.db.stats(persistent_start, actual_only=True)
        virtual = await self.db.stats(persistent_start, actual_only=False)
        today = await self.db.stats(today_start, actual_only=True)
        balance = float(await self.db.get("current_balance", "0"))
        actual_total = (actual["wins"] or 0) + (actual["losses"] or 0) + (actual["ties"] or 0)
        virtual_decided = (virtual["wins"] or 0) + (virtual["losses"] or 0)
        win_rate = ((virtual["wins"] or 0) / virtual_decided * 100) if virtual_decided else 0
        return (
            "\n\n📊 <b>THỐNG KÊ TỪ LẦN RESET</b>\n"
            f"🟢 Thắng: <b>{actual['wins'] or 0}</b> | 🔴 Thua: <b>{actual['losses'] or 0}</b> | ➖ Hòa: <b>{actual['ties'] or 0}</b>\n"
            f"📋 Tổng lệnh thực tế: <b>{actual_total}</b>\n"
            f"💰 Tổng tiền đã đặt: <b>{actual['staked']:.2f} USDT</b>\n"
            f"💵 Lãi/lỗ ròng: <b>{actual['pnl']:+.2f} USDT</b>\n"
            f"💳 Số dư hiện tại: <b>{balance:.2f} USDT</b>\n"
            f"📅 Hôm nay: {today['wins'] or 0} thắng | {today['losses'] or 0} thua | {today['ties'] or 0} hòa\n\n"
            "📡 <b>PHÂN TÍCH TỪ LẦN RESET</b>\n"
            f"Thắng: {virtual['wins'] or 0} | Thua: {virtual['losses'] or 0} | Hòa: {virtual['ties'] or 0}\n"
            f"Tỷ lệ thắng: {win_rate:.1f}%"
        )

    async def signal_text(self, p: Prediction) -> str:
        local_open = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp(p.market_close_time / 1000, self.config.timezone)
        label = "🟢 𝗠𝗨𝗔 𝗧Ă𝗡𝗚" if p.direction == "UP" else "🔴 𝗠𝗨𝗔 𝗚𝗜Ả𝗠"
        confidence_block = self.confidence_block(p.confidence)
        history_side = "tăng" if p.direction == "UP" else "giảm"
        history_rate = p.confidence * 100
        m1_analysis = candle_analysis(list(self.m1), "M1")
        m5_analysis = candle_analysis(list(self.m5), "M5")
        return (
            "📥 <b>TIN NHẮN VÀO LỆNH</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{label}: {p.bet_amount:.2f} USDT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ Phiên: {local_open:%H:%M}–{local_close:%H:%M}\n"
            f"🎯 Target: <code>{p.target_price:,.2f}</code> USDT\n"
            f"💵 Giá lúc báo: <code>{p.signal_price:,.2f}</code> USDT\n"
            f"\n{confidence_block}\n\n"
            f"🔎 M1: {p.m1_probability * 100:.1f}% tăng | M5: {p.m5_probability * 100:.1f}% tăng\n"
            f"🕯 {m1_analysis}\n"
            f"🕯 {m5_analysis}\n"
            f"🧩 Mẫu tương tự nghiêng {history_side}: <b>{history_rate:.1f}%</b> ({p.pattern_samples} mẫu)\n"
            f"🔢 Tầng tiền: <b>LỆNH {p.bet_step}</b>"
            + await self.stats_text()
        )

    async def result_text(self, row, close_price: float, result: str, pnl: float) -> str:
        return {"WIN": "✅ <b>ĐÃ THẮNG</b>", "LOSS": "❌ <b>ĐÃ THUA</b>", "TIE": "➖ <b>ĐÃ HÒA</b>"}[result]

    @staticmethod
    def confidence_block(confidence: float) -> str:
        if confidence >= 0.65:
            icon, quality = "🟢", "CAO"
        elif confidence >= 0.57:
            icon, quality = "🟡", "TRUNG BÌNH"
        else:
            icon, quality = "🔴", "THẤP"
        return (
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{icon} <b>ĐỘ TIN CẬY: {quality} – {confidence * 100:.1f}%</b>\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

    async def handle_telegram(self, kind: str, value: str, raw: dict) -> None:
        if kind == "callback":
            if value == "stop":
                await self.db.set("manual_enabled", 0)
                await self.db.set("pause_started_at", int(datetime.now(timezone.utc).timestamp() * 1000))
                await self.telegram.send(
                    "🔴 <b>ĐÃ DỪNG GỬI LỆNH</b>\nTool vẫn phân tích và chấm kết quả 24/7.",
                    enabled=False,
                )
            elif value == "start":
                await self.db.set("manual_enabled", 1)
                await self.telegram.send("🟢 <b>BOT ĐANG CHẠY</b>" + await self.stats_text(), enabled=True)
            elif value == "status":
                enabled = await self.signals_enabled()
                await self.telegram.send(await self.status_text(), enabled=enabled)
            elif value == "setbet_help":
                await self.db.set("awaiting_setbet", 1)
                await self.telegram.ask(
                    "💵 <b>NHẬP VỐN LỆNH 1</b>\n\n"
                    "Ví dụ nhập <code>2</code> thì:\n"
                    "• Lệnh 1 = 2 USDT\n"
                    "• Lệnh 2 = 4 USDT\n\n"
                    "Hãy nhập một số rồi bấm Gửi.",
                    "Ví dụ: 2",
                )
            elif value == "reset_stats":
                await self.telegram.ask_reset_confirmation()
            elif value == "reset_cancel":
                await self.telegram.send("❎ Đã hủy reset thống kê.")
            elif value == "reset_confirm":
                pending = await self.db.pending()
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                # Lệnh đang dở vẫn được tính sau khi chấm; lịch sử trước đó bị ẩn khỏi thống kê mới.
                reset_at = min((int(row["market_open_time"]) for row in pending), default=now_ms)
                await self.db.set("stats_reset_at", reset_at)
                await self.db.set("current_balance", 0)
                await self.db.set("bet_step", 1)
                await self.db.set("risk_cycle_losses", 0)
                await self.db.set("risk_pause_until", 0)
                await self.db.event("STATS_RESET", {"reset_at": reset_at, "requested_at": now_ms})
                enabled = await self.signals_enabled()
                await self.telegram.send(
                    "♻️ <b>ĐÃ RESET THỐNG KÊ VỀ 0</b>\n"
                    "Thắng: 0 | Thua: 0 | Lãi/lỗ: 0.00 USDT\n"
                    "Tầng tiền: LỆNH 1",
                    enabled=enabled,
                )
            return
        parts = value.split()
        command = parts[0].lower()
        try:
            awaiting_setbet = await self.db.get("awaiting_setbet", "0") == "1"
            if awaiting_setbet and command not in ("/cancel", "/status", "/start"):
                amount = float(value.replace(",", "."))
                if amount <= 0 or amount * 2 > self.config.max_bet:
                    raise ValueError
                await self.db.set("base_bet", amount)
                await self.db.set("awaiting_setbet", 0)
                step = int(await self.db.get("bet_step", "1"))
                next_bet = min(amount * (2 if step == 2 else 1), self.config.max_bet)
                await self.telegram.send(
                    f"✅ <b>ĐÃ ĐỔI VỐN THÀNH CÔNG</b>\n"
                    f"Lệnh 1: <b>{amount:.2f} USDT</b>\n"
                    f"Lệnh 2: <b>{amount * 2:.2f} USDT</b>\n"
                    f"Lệnh tiếp theo: <b>{next_bet:.2f} USDT – LỆNH {step}</b>"
                )
            elif command == "/cancel":
                await self.db.set("awaiting_setbet", 0)
                await self.telegram.send("Đã hủy nhập vốn.")
            elif command == "/setbet" and len(parts) == 2:
                amount = float(parts[1])
                if amount <= 0 or amount * 2 > self.config.max_bet:
                    raise ValueError
                await self.db.set("base_bet", amount)
                await self.db.set("awaiting_setbet", 0)
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
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        data_age = (now_ms - self.last_market_event_ms) / 1000 if self.last_market_event_ms else None
        trade_age = (now_ms - self.last_trade_event_ms) / 1000 if self.last_trade_event_ms else None
        connected = data_age is not None and data_age <= 15
        tick_connected = trade_age is not None and trade_age <= 3
        if self.last_market_event_ms:
            last_data = datetime.fromtimestamp(self.last_market_event_ms / 1000, self.config.timezone).strftime("%H:%M:%S")
        else:
            last_data = "chưa nhận được"
        if self.last_trade_event_ms:
            last_tick = datetime.fromtimestamp(self.last_trade_event_ms / 1000, self.config.timezone).strftime("%H:%M:%S.%f")[:-3]
        else:
            last_tick = "chưa nhận được"
        return (
            "🤖 <b>BÁO CÁO BOT</b>\n"
            f"Bộ máy phân tích: <b>{'🟢 ĐANG HOẠT ĐỘNG' if connected else '🔴 MẤT DỮ LIỆU'}</b>\n"
            f"Kết nối Binance: <b>{'BÌNH THƯỜNG' if connected else 'ĐANG KẾT NỐI LẠI'}</b>\n"
            f"Luồng tick aggTrade: <b>{'🟢 ĐANG NHẢY' if tick_connected else '🔴 KHÔNG CÓ TICK MỚI'}</b>\n"
            f"Tick gần nhất: <b>{last_tick}</b> | Đã nhận: <b>{self.trade_ticks:,}</b>\n"
            f"Lần nhận dữ liệu gần nhất: <b>{last_data}</b>\n"
            f"Trạng thái gửi lệnh: <b>{'ĐANG CHẠY' if enabled else 'ĐANG DỪNG'}</b>\n"
            f"Giá BTC: <code>{self.live_price:,.2f}</code> USDT\n"
            f"Vốn gốc: <b>{base:.2f}</b> | Tầng hiện tại: <b>LỆNH {step}</b>" + await self.stats_text()
        )

    async def run(self) -> None:
        await self.setup()
        enabled = await self.signals_enabled()
        await self.telegram.send(
            "🤖 <b>BOT ĐÃ KHỞI ĐỘNG</b>\nĐang nhận nến Binance và phân tích 24/7.",
            enabled=enabled,
        )
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
