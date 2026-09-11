from __future__ import annotations

import runtime_v356 as v356


APP_VERSION = "3.5.7"

# Keep visible base-runtime version in sync while older modules retain their own
# frozen release constants for regression tests.
v356.v355.v354.v353.v352.v351.v35.v34.v33.base_runtime.APP_VERSION = APP_VERSION


class TradingSignalBotV3(v356.TradingSignalBotV3):
    """V3.5.7: count only truly consecutive same-result two-order pairs.

    Pairing is greedy left-to-right and does NOT use fixed (1,2), (3,4), ...
    slots. If two neighboring settled real orders have the same WIN/LOSS result,
    they form one pair and both are consumed. If they differ, advance one order
    so the next order can still pair with its immediate neighbor.

    Examples:
      W W L W L W -> 1 win pair, 0 loss pairs
      W L L W     -> 0 win pairs, 1 loss pair
      W W W W     -> 2 win pairs
    """

    async def pair_stats_since_reset(self) -> dict:
        reset_at = int(await self.db.get("stats_reset_at", "0"))
        rows = await (await self.db.conn.execute(
            """SELECT result FROM signals
               WHERE market_open_time>=? AND status='SETTLED' AND actual=1
               ORDER BY market_open_time""",
            (max(0, reset_at),),
        )).fetchall()
        results = [row["result"] for row in rows]

        win_pairs = 0
        loss_pairs = 0
        used = 0
        index = 0
        while index + 1 < len(results):
            first = results[index]
            second = results[index + 1]
            if first == second == "WIN":
                win_pairs += 1
                used += 2
                index += 2
                continue
            if first == second == "LOSS":
                loss_pairs += 1
                used += 2
                index += 2
                continue
            # Do not consume the second order on a mismatch. It must remain
            # eligible to pair with the immediately following order.
            index += 1

        unmatched = len(results) - used
        return {
            "win_pairs": win_pairs,
            "loss_pairs": loss_pairs,
            "other_pairs": unmatched // 2,
            "complete_pairs": win_pairs + loss_pairs,
            "unpaired": unmatched,
        }

    async def stats_text(self) -> str:
        # Reuse the parent report but replace only the pair section so the wording
        # matches the new adjacent-pair rule and does not imply fixed pair slots.
        text = await v356.v355.v354.v353.v352.v351.v35.v34.v33.TradingSignalBotV3.stats_text(self)
        pairs = await self.pair_stats_since_reset()
        return (
            text
            + "\n\n🔗 <b>CẶP 2 LỆNH LIỀN NHAU</b>\n"
            + f"✅ Cặp thắng liên tiếp: <b>{pairs['win_pairs']}</b>\n"
            + f"❌ Cặp thua liên tiếp: <b>{pairs['loss_pairs']}</b>\n"
            + f"➖ Lệnh chưa ghép thành cặp cùng kết quả: <b>{pairs['unpaired']}</b>"
        )
