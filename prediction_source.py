from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

RED = "R"
GREEN = "G"
INTERVAL_S = 300


@dataclass(slots=True, frozen=True)
class ResolvedPredictionRound:
    open_time: int
    close_time: int
    color: str
    slug: str
    source: str = "predict.fun/Binance Prediction"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ")


def _side_to_color(value: Any) -> str | None:
    text = _norm(value)
    if not text:
        return None
    if text in {"up", "yes", "green", "higher", "above"}:
        return GREEN
    if text in {"down", "no", "red", "lower", "below"}:
        return RED
    if " up" in f" {text}" or text.startswith("up "):
        return GREEN
    if " down" in f" {text}" or text.startswith("down "):
        return RED
    return None


def parse_prediction_resolution(payload: dict[str, Any]) -> str | None:
    """Return G/R only when the prediction market itself has a resolved winner.

    Binance Prediction's orderbook documentation identifies Predict.fun as the
    upstream market. The category payload used by Predict.fun exposes one binary
    market under data.markets and a resolution payload after settlement.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    markets = data.get("markets") or []
    if not markets and isinstance(data.get("market"), dict):
        markets = [data["market"]]
    if not markets:
        return None
    market = markets[0] if isinstance(markets[0], dict) else {}
    resolution = market.get("resolution")

    if isinstance(resolution, dict):
        for key in (
            "winningOutcome",
            "winning_outcome",
            "winner",
            "result",
            "outcome",
            "marketTitle",
        ):
            color = _side_to_color(resolution.get(key))
            if color:
                return color

        outcomes = market.get("outcomes") or []
        payouts = resolution.get("payouts") or resolution.get("indexSetPayouts")
        if isinstance(payouts, list) and isinstance(outcomes, list):
            for index, payout in enumerate(payouts):
                if index >= len(outcomes):
                    break
                try:
                    won = float(payout) >= 0.99
                except (TypeError, ValueError):
                    won = False
                if won and isinstance(outcomes[index], dict):
                    color = _side_to_color(outcomes[index].get("name"))
                    if color:
                        return color

        for key, value in resolution.items():
            color = _side_to_color(key)
            if not color:
                continue
            try:
                if float(value) >= 0.99:
                    return color
            except (TypeError, ValueError):
                pass

    status = _norm(market.get("tradingStatus") or market.get("status"))
    if status not in {"resolved", "settled", "closed", "ended", "finalized"}:
        return None

    # Last-resort settled-market parser: one outcome often settles at ~1 and
    # the other at ~0. Never use this while the market is OPEN.
    for outcome in market.get("outcomes") or []:
        if not isinstance(outcome, dict):
            continue
        color = _side_to_color(outcome.get("name"))
        if not color:
            continue
        candidates = [
            outcome.get("payout"),
            outcome.get("finalPrice"),
            outcome.get("settlementPrice"),
            (outcome.get("bestAsk") or {}).get("price") if isinstance(outcome.get("bestAsk"), dict) else None,
            (outcome.get("bestBid") or {}).get("price") if isinstance(outcome.get("bestBid"), dict) else None,
        ]
        for candidate in candidates:
            try:
                if candidate is not None and float(candidate) >= 0.99:
                    return color
            except (TypeError, ValueError):
                continue
    return None


class PredictionHistorySource:
    """Fetch resolved BTC 5-minute Up/Down rounds used by Binance Prediction.

    The URL slug is btc-updown-5m-<UTC window start seconds>. Settled rounds are
    cached forever; only the newest unresolved window is retried on later polls.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_base: str = "https://api.predict.fun",
        api_key: str = "",
        *,
        max_concurrency: int = 8,
    ):
        self.session = session
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key.strip()
        self.max_concurrency = max(1, int(max_concurrency))
        self._cache: dict[int, ResolvedPredictionRound] = {}
        self.last_error = ""
        self.last_http_status: int | None = None

    @staticmethod
    def slug(start_s: int) -> str:
        return f"btc-updown-5m-{int(start_s)}"

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "BossVaoLenh/4.1"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def fetch_one(self, start_s: int) -> ResolvedPredictionRound | None:
        start_s = int(start_s)
        cached = self._cache.get(start_s)
        if cached is not None:
            return cached
        slug = self.slug(start_s)
        url = f"{self.api_base}/v1/categories/{slug}"
        try:
            async with self.session.get(url, headers=self.headers()) as response:
                self.last_http_status = response.status
                if response.status in (401, 403):
                    self.last_error = (
                        f"Prediction API HTTP {response.status}. "
                        "Hãy điền PREDICT_API_KEY nếu endpoint yêu cầu khóa."
                    )
                    return None
                if response.status == 404:
                    return None
                if response.status >= 400:
                    body = await response.text()
                    self.last_error = f"Prediction API HTTP {response.status}: {body[:160]}"
                    return None
                payload = await response.json(content_type=None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = f"Prediction API: {type(exc).__name__}: {exc}"
            return None

        color = parse_prediction_resolution(payload if isinstance(payload, dict) else {})
        if not color:
            return None
        round_ = ResolvedPredictionRound(
            open_time=start_s * 1000,
            close_time=(start_s + INTERVAL_S) * 1000 - 1,
            color=color,
            slug=slug,
        )
        self._cache[start_s] = round_
        self.last_error = ""
        return round_

    async def recent(self, limit: int = 40) -> list[ResolvedPredictionRound]:
        limit = max(5, min(120, int(limit)))
        now_s = int(time.time())
        latest_closed_start = (now_s // INTERVAL_S) * INTERVAL_S - INTERVAL_S
        # Ask for a few extra windows because a just-closed round can remain
        # unresolved for a short time before the venue publishes settlement.
        starts = [
            latest_closed_start - i * INTERVAL_S
            for i in range(limit + 4)
        ]
        starts.reverse()
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def load(start_s: int):
            async with semaphore:
                return await self.fetch_one(start_s)

        loaded = await asyncio.gather(*(load(ts) for ts in starts))
        rounds = [item for item in loaded if item is not None]
        rounds.sort(key=lambda item: item.open_time)
        return rounds[-limit:]
