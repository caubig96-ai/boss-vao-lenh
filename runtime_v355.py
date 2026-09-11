from __future__ import annotations

import asyncio

import runtime_v354 as v354


APP_VERSION = "3.5.5"

# Keep inherited visible version strings in sync.
v354.APP_VERSION = APP_VERSION
v354.v353.APP_VERSION = APP_VERSION
v354.v353.v352.v351.v35.v34.v33.APP_VERSION = APP_VERSION
v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


class TradingSignalBotV3(v354.TradingSignalBotV3):
    """V3.5.5: exactly two entry-time Telegram messages per M5 session.

    1) one compact signal card with all controls + CHI TIẾT
    2) one short action/advice line

    The previous get-then-set action guard could race when the same M5 decision was
    scheduled twice at nearly the same time. Both tasks could read 0 before either
    wrote 1, producing two identical action messages. This version serializes
    decision handling inside one process and uses an atomic SQLite INSERT OR IGNORE
    claim for the action message, which also protects against two local processes
    sharing the same database.
    """

    def __init__(self, config):
        super().__init__(config)
        self._decision_send_lock = asyncio.Lock()

    async def _claim_action_message(self, open_time: int) -> bool:
        key = f"action_message_claim:{open_time}"
        cursor = await self.db.conn.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
            (key, "sending"),
        )
        await self.db.conn.commit()
        return cursor.rowcount == 1

    async def _mark_action_sent(self, open_time: int) -> None:
        await self.db.set(f"action_message_claim:{open_time}", "sent")
        # Preserve the V3.5.3 compatibility key so older builds cannot resend
        # the action if the user briefly launches an older EXE against this DB.
        await self.db.set(f"action_message_sent:{open_time}", "1")

    async def _release_action_claim(self, open_time: int) -> None:
        await self.db.conn.execute(
            "DELETE FROM settings WHERE key=? AND value='sending'",
            (f"action_message_claim:{open_time}",),
        )
        await self.db.conn.commit()

    async def make_decision(self, open_time: int, delay: float) -> None:
        # Serialize duplicate scheduler callbacks for the same/nearby M5 boundary.
        async with self._decision_send_lock:
            # Run through V3.5.2 decision flow (signal card only), bypassing the
            # V3.5.3 get/set action sender that is vulnerable to a race.
            await v354.v353.v352.TradingSignalBotV3.make_decision(self, open_time, delay)

            row = await self._row_for_signal(open_time)
            if row is None or row["telegram_message_id"] is None:
                return

            # If any earlier V3.5.3/V3.5.4 task already sent the action, do not
            # create another one after an in-place upgrade.
            if await self.db.get(f"action_message_sent:{open_time}", "0") == "1":
                return

            if not await self._claim_action_message(open_time):
                return

            prediction = self._prediction_from_row(row)
            try:
                await self.telegram.send(await self._action_message(prediction), keyboard=False)
                await self._mark_action_sent(open_time)
                await self.db.event(
                    "ACTION_MESSAGE_SENT_ONCE",
                    {
                        "open_time": open_time,
                        "direction": prediction.direction,
                        "bet_step": prediction.bet_step,
                    },
                )
            except Exception as exc:
                # Release only an unfinished claim so normal retry remains possible.
                await self._release_action_claim(open_time)
                await self.db.event(
                    "ACTION_MESSAGE_SEND_ERROR",
                    {"open_time": open_time, "error": str(exc)},
                )
