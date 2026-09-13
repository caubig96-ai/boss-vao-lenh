from __future__ import annotations

import asyncio
import html
import logging
import math
from datetime import datetime

import runtime_v373 as v373


APP_VERSION = "3.7.4"
AGREEMENT_FALLBACK_THRESHOLD = 3
AGREEMENT_POLICY_MIN_SAMPLES = 20
log = logging.getLogger("boss-vao-lenh-v374")

# Keep inherited visible version text current while preserving frozen release constants.
v373.v372.v371.v37.v361.v36.v357.v356.v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


def _win_rate(wins: int, losses: int) -> float:
    decided = wins + losses
    return wins / decided * 100.0 if decided else 0.0


def _wilson_lower_bound(wins: int, losses: int, z: float = 1.645) -> float:
    """90% Wilson lower bound used only to choose a stable historical threshold."""
    n = wins + losses
    if n <= 0:
        return 0.0
    p = wins / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = p + z2 / (2.0 * n)
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    return max(0.0, (center - margin) / denominator)


class CompactTelegramBotV374(v373.CompactTelegramBotV373):
    """Telegram controls that acknowledge taps immediately and expose polling conflicts."""

    def __init__(self, token: str, chat_id: str, handler, offset_saver=None):
        super().__init__(token, chat_id, handler, offset_saver)
        self._conflict_warning_sent = False

    async def open(self) -> None:
        await super().open()
        # A stale webhook makes getUpdates return 409 forever. The desktop bot uses
        # long polling, so remove an old webhook proactively without dropping updates.
        try:
            await self._call("deleteWebhook", {"drop_pending_updates": False})
        except Exception as exc:
            self.last_error = f"deleteWebhook: {exc}"

    async def _send_poll_conflict_warning(self, description: str) -> None:
        if self._conflict_warning_sent:
            return
        self._conflict_warning_sent = True
        try:
            await self._call("sendMessage", {
                "chat_id": self.chat_id,
                "text": (
                    "⚠️ <b>ĐIỀU KHIỂN TELEGRAM ĐANG BỊ XUNG ĐỘT</b>\n"
                    "Có một bot/process khác đang dùng cùng Telegram token để nhận nút bấm. "
                    "Hãy tắt bản cũ hoặc cloud dùng cùng token. Bot vẫn có thể gửi tin ra nhưng nút sẽ chập chờn cho đến khi chỉ còn 1 bộ nhận."
                ),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
        except Exception:
            log.exception("Could not report Telegram polling conflict: %s", description)

    async def _dispatch(self, update: dict) -> None:
        callback = update.get("callback_query")
        if callback:
            callback_id = callback.get("id", "")
            if str(callback.get("from", {}).get("id")) != self.chat_id:
                await self.answer_callback(callback_id, "Không có quyền")
                return

            # Telegram shows a spinner until answerCallbackQuery. Answer first so a
            # heavy report query never looks like a dead button.
            await self.answer_callback(callback_id, "Đang xử lý…")
            try:
                await self.handler("callback", callback.get("data", ""), update)
            except Exception as exc:
                self.last_error = f"callback: {type(exc).__name__}: {exc}"
                log.exception("Telegram callback failed: %s", callback.get("data", ""))
                try:
                    await self._call("sendMessage", {
                        "chat_id": self.chat_id,
                        "text": f"⚠️ <b>NÚT BẤM BỊ LỖI</b>\n<code>{html.escape(type(exc).__name__ + ': ' + str(exc))}</code>",
                        "parse_mode": "HTML",
                    })
                except Exception:
                    pass
            return

        message = update.get("message", {})
        if str(message.get("chat", {}).get("id")) != self.chat_id:
            return
        text = message.get("text", "").strip()
        if text:
            try:
                await self.handler("message", html.escape(text), update)
            except Exception as exc:
                self.last_error = f"message: {type(exc).__name__}: {exc}"
                log.exception("Telegram message handler failed")

    async def poll(self) -> None:
        """Long-poll updates without losing a button before its handler finishes."""
        while True:
            try:
                if not self.session:
                    await asyncio.sleep(1)
                    continue
                params = {
                    "offset": self.offset + 1,
                    "timeout": 25,
                    "allowed_updates": ["message", "callback_query"],
                }
                async with self.session.get(f"{self.base_url}/getUpdates", params=params) as response:
                    data = await response.json(content_type=None)
                if not response.ok or not data.get("ok"):
                    description = str(data.get("description", data))
                    conflict = response.status == 409 or "Conflict" in description
                    self.poll_conflict = conflict
                    if conflict and "webhook" in description.lower():
                        try:
                            await self._call("deleteWebhook", {"drop_pending_updates": False})
                        except Exception:
                            pass
                    if conflict:
                        await self._send_poll_conflict_warning(description)
                    raise RuntimeError(description)

                self.poll_conflict = False
                self.last_error = ""
                for update in data.get("result", []):
                    update_id = int(update["update_id"])
                    # Handle first, then persist the offset. A callback that throws
                    # must not disappear silently before the user receives feedback.
                    await self._dispatch(update)
                    self.offset = max(self.offset, update_id)
                    await self._save_offset()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                log.warning("Telegram polling lỗi: %s", exc)
                await asyncio.sleep(3)


class TradingSignalBotV3(v373.TradingSignalBotV3):
    """V3.7.4: reliable Telegram controls + performance by 2/6..6/6 agreement."""

    def __init__(self, config):
        super().__init__(config)
        self.telegram = CompactTelegramBotV374(
            config.telegram_token,
            config.telegram_chat_id,
            self.handle_telegram,
            self._save_telegram_offset,
        )

    async def agreement_stats_since_reset(self) -> dict[int, dict[str, int | float]]:
        reset_at = int(await self.db.get("stats_reset_at", "0"))
        rows = await (await self.db.conn.execute(
            """SELECT agreement,
                      SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
                      SUM(CASE WHEN result='TIE' THEN 1 ELSE 0 END) AS ties
               FROM color_predictions
               WHERE status='SETTLED' AND market_open_time>=? AND agreement BETWEEN 2 AND 6
               GROUP BY agreement""",
            (max(0, reset_at),),
        )).fetchall()
        result: dict[int, dict[str, int | float]] = {
            level: {"wins": 0, "losses": 0, "ties": 0, "decided": 0, "win_rate": 0.0}
            for level in range(2, 7)
        }
        for row in rows:
            level = int(row["agreement"])
            wins = int(row["wins"] or 0)
            losses = int(row["losses"] or 0)
            ties = int(row["ties"] or 0)
            result[level] = {
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "decided": wins + losses,
                "win_rate": _win_rate(wins, losses),
            }
        return result

    @staticmethod
    def _threshold_stats(exact: dict[int, dict[str, int | float]], threshold: int) -> dict[str, int | float]:
        wins = sum(int(exact[level]["wins"]) for level in range(threshold, 7))
        losses = sum(int(exact[level]["losses"]) for level in range(threshold, 7))
        ties = sum(int(exact[level]["ties"]) for level in range(threshold, 7))
        return {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "decided": wins + losses,
            "win_rate": _win_rate(wins, losses),
            "wilson": _wilson_lower_bound(wins, losses),
        }

    async def agreement_entry_policy(self) -> tuple[int, dict[str, int | float], dict[int, dict[str, int | float]]]:
        """Choose >=3/6..>=6/6 from settled history; fall back to >=3/6 until mature."""
        exact = await self.agreement_stats_since_reset()
        candidates: list[tuple[float, float, int, int, dict[str, int | float]]] = []
        for threshold in range(3, 7):
            stats = self._threshold_stats(exact, threshold)
            if int(stats["decided"]) < AGREEMENT_POLICY_MIN_SAMPLES:
                continue
            # Prefer the strongest lower-confidence bound, then WR, sample size,
            # then the lower threshold if otherwise tied (more usable signals).
            candidates.append((
                float(stats["wilson"]),
                float(stats["win_rate"]),
                int(stats["decided"]),
                -threshold,
                stats,
            ))
        if not candidates:
            threshold = AGREEMENT_FALLBACK_THRESHOLD
            return threshold, self._threshold_stats(exact, threshold), exact
        best = max(candidates, key=lambda item: item[:4])
        threshold = -int(best[3])
        return threshold, best[4], exact

    @staticmethod
    def _agreement_line(level: int, stats: dict[str, int | float]) -> str:
        wins = int(stats["wins"])
        losses = int(stats["losses"])
        decided = wins + losses
        rate = float(stats["win_rate"])
        rate_text = f"{rate:.1f}%" if decided else "--"
        return f"{level}/6: ✅ {wins} thắng • ❌ {losses} thua • <b>{rate_text}</b>"

    async def signal_text(self, p) -> str:
        stats, _qualified = await self._signal_calibration(p)
        pairs = await self.pair_stats_since_reset()
        totals = await self._entry_totals_since_reset()
        color_row = await self._color_prediction_row(int(p.market_open_time))
        agreement = int(color_row["agreement"]) if color_row is not None else 0
        previous_icon, previous_color = await self._previous_candle_label(int(p.market_open_time))
        threshold, threshold_stats, exact = await self.agreement_entry_policy()

        local_open = datetime.fromtimestamp(p.market_open_time / 1000, self.config.timezone)
        local_close = datetime.fromtimestamp((p.market_close_time + 1) / 1000, self.config.timezone)
        direction = "MUA TĂNG" if p.direction == "UP" else "MUA GIẢM"
        direction_icon = "🟢" if p.direction == "UP" else "🔴"
        if int(stats.get("decided", 0)) > 0:
            expected = float(stats.get("win_rate", 0.0))
        else:
            expected = float(p.confidence) * 100.0

        agreement_lines = "\n".join(self._agreement_line(level, exact[level]) for level in range(2, 7))
        policy_decided = int(threshold_stats["decided"])
        policy_rate = float(threshold_stats["win_rate"])
        policy_text = (
            f"≥{threshold}/6 • {policy_rate:.1f}% ({int(threshold_stats['wins'])}T/{int(threshold_stats['losses'])}B)"
            if policy_decided else f"≥{threshold}/6 • đang thu thập mẫu"
        )

        return (
            f"{direction_icon} <b>{direction}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {local_open:%H:%M}–{local_close:%H:%M}\n"
            f"📊 Dự kiến thắng: <b>{expected:.1f}%</b>\n"
            f"📋 Tổng: ✅ {totals['wins']} thắng • ❌ {totals['losses']} thua\n"
            f"🔗 Cặp: ✅ {pairs['win_pairs']} thắng • ❌ {pairs['loss_pairs']} thua\n"
            f"💵 Giá: <code>{p.signal_price:,.2f}</code> • <b>LỆNH {p.bet_step}</b>: {p.bet_amount:.2f} USDT\n"
            f"🧩 Hiện tại: <b>{agreement}/6</b> cách cùng hướng\n"
            "📚 <b>Lịch sử theo mức cùng hướng:</b>\n"
            f"{agreement_lines}\n"
            f"🎯 Ngưỡng MUA NGAY tự chọn: <b>{policy_text}</b>\n"
            f"🕯 Nến trước: {previous_icon} <b>{previous_color}</b>"
        )

    async def threshold_stats_text(self) -> str:
        threshold, threshold_stats, exact = await self.agreement_entry_policy()
        lines = [
            f"📈 <b>HIỆU SUẤT ĐỒNG THUẬN • V{APP_VERSION}</b>",
            "Thống kê từ lần RESET gần nhất; hòa không tính vào % thắng.",
            "",
        ]
        lines.extend(self._agreement_line(level, exact[level]) for level in range(2, 7))
        lines.append("")
        lines.append("<b>Hiệu suất nếu dùng ngưỡng trở lên:</b>")
        for candidate in range(3, 7):
            stats = self._threshold_stats(exact, candidate)
            decided = int(stats["decided"])
            rate_text = f"{float(stats['win_rate']):.1f}%" if decided else "--"
            lines.append(
                f"≥{candidate}/6: ✅ {int(stats['wins'])} • ❌ {int(stats['losses'])} • <b>{rate_text}</b>"
            )
        lines.append("")
        if int(threshold_stats["decided"]) >= AGREEMENT_POLICY_MIN_SAMPLES:
            lines.append(
                f"🎯 <b>NGƯỠNG MUA NGAY ĐANG CHỌN: ≥{threshold}/6</b> "
                f"({float(threshold_stats['win_rate']):.1f}% • {int(threshold_stats['decided'])} mẫu)"
            )
            lines.append("Tool chọn theo hiệu suất lịch sử đã chấm và độ ổn định mẫu, không chỉ nhìn % cao nhất.")
        else:
            lines.append(
                f"🎯 <b>NGƯỠNG TẠM THỜI: ≥{AGREEMENT_FALLBACK_THRESHOLD}/6</b> • "
                f"cần ≥{AGREEMENT_POLICY_MIN_SAMPLES} kết quả để tự tối ưu ngưỡng."
            )
        return "\n".join(lines)

    async def make_decision(self, open_time: int, delay: float) -> None:
        """One color forecast; MUA NGAY uses the adaptive agreement threshold."""
        async with self._decision_send_lock:
            await asyncio.sleep(delay)
            try:
                live = self.live_m5
                if live is None or live.open_time != open_time:
                    try:
                        await self.rest_snapshot()
                    except Exception:
                        pass
                    live = self.live_m5
                if live is None or live.open_time != open_time:
                    self.last_decision_state = "LỖI: KHÔNG CÓ NẾN M5 LIVE"
                    await self.db.event("COLOR_DECISION_SKIPPED_NO_MARKET", {"open_time": open_time})
                    return
                if self.live_price <= 0:
                    self.live_price = live.close

                history = await self._closed_m5_history(open_time)
                forecast = v373.v372.v371.v37.predict_next_color(history)
                threshold, threshold_stats, _exact = await self.agreement_entry_policy()
                recommended = int(forecast.agreement) >= int(threshold)
                await self._save_color_prediction(open_time, live.close_time, forecast, recommended)

                actual = await self.signals_enabled()
                base_bet = float(await self.db.get("base_bet", str(self.config.base_bet)))
                step = int(await self.db.get("bet_step", "1"))
                bet = min(base_bet * (2 if step == 2 else 1), self.config.max_bet)
                prediction = v373.v372.v371.v37.Prediction(
                    int(open_time), int(live.close_time), float(live.open), float(self.live_price),
                    forecast.direction, forecast.confidence, forecast.green_probability,
                    forecast.green_probability, forecast.sequence_samples + forecast.knn_samples,
                    bet, step, bool(actual),
                )
                created = await self.db.create_signal(prediction)
                self.last_decision_open = open_time
                self.last_decision_state = (
                    f"COLOR {forecast.color} {forecast.confidence * 100:.1f}% • "
                    f"{forecast.agreement}/6 • BUY>={threshold}/6"
                )

                row = await self._row_for_signal(open_time)
                row = await self._ensure_primary_message(row)
                await self.db.event("SINGLE_COLOR_DECISION_CREATED", {
                    "open_time": int(open_time),
                    "direction": forecast.direction,
                    "green_probability": forecast.green_probability,
                    "confidence": forecast.confidence,
                    "agreement": forecast.agreement,
                    "entry_threshold": threshold,
                    "threshold_decided": int(threshold_stats["decided"]),
                    "threshold_win_rate": float(threshold_stats["win_rate"]),
                    "history_candles": len(history),
                    "recommended": recommended,
                    "created": created,
                    "actual": bool(actual),
                    "legacy_modes_created": 0,
                })
            except Exception as exc:
                self.last_decision_state = f"LỖI COLOR: {type(exc).__name__}"
                log.exception("V3.7.4 color decision failed for %s", open_time)
                try:
                    await self.db.event("SINGLE_COLOR_DECISION_ERROR", {"open_time": open_time, "error": str(exc)})
                except Exception:
                    pass
            finally:
                self.decision_tasks.pop(open_time, None)

            await self._ensure_action_message(open_time)

    async def status_text(self) -> str:
        text = await super().status_text()
        callback_state = "⚠️ XUNG ĐỘT getUpdates" if self.telegram.poll_conflict else "✅ SẴN SÀNG"
        threshold, threshold_stats, _exact = await self.agreement_entry_policy()
        return (
            text
            + f"\n🎛 Điều khiển Telegram: <b>{callback_state}</b>"
            + f"\n🎯 Ngưỡng MUA NGAY: <b>≥{threshold}/6</b>"
            + (
                f" • {float(threshold_stats['win_rate']):.1f}%/{int(threshold_stats['decided'])} mẫu"
                if int(threshold_stats["decided"]) else " • đang thu thập mẫu"
            )
        )

    async def safe_startup_message(self) -> None:
        try:
            enabled = await self.db.get("manual_enabled", "1") == "1"
            threshold, _stats, _exact = await self.agreement_entry_policy()
            await self.telegram.send(
                f"🤖 <b>BOT V{APP_VERSION} ĐÃ CHẠY</b>\n"
                "🎨 COLOR ENGINE • 6 cách phân tích nến\n"
                f"🎯 Ngưỡng MUA NGAY hiện tại: <b>≥{threshold}/6</b>\n"
                "🎛 Nút Báo cáo / Đổi vốn / Tỷ lệ / Reset đã bật bộ xử lý callback mới.",
                enabled=enabled,
            )
        except Exception as exc:
            self.telegram.last_error = str(exc)
            log.warning("Startup Telegram send failed; market engine continues: %s", exc)
