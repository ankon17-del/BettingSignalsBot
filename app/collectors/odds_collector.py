from dataclasses import dataclass
from typing import Any

import aiohttp


@dataclass(slots=True)
class OddsSelection:
    sport: str
    league: str
    match_name: str
    home_team: str
    away_team: str
    market: str
    bookmaker_name: str
    odds: float
    source_event_id: str | None = None
    source_market_id: str | None = None
    raw_payload: dict[str, Any] | None = None


class OlimpOddsCollector:
    def __init__(self, line_url: str, timeout_seconds: float = 10.0, sport: str = "football") -> None:
        self.line_url = line_url
        self.timeout_seconds = timeout_seconds
        self.sport = sport

    async def fetch_raw(self) -> dict[str, Any] | list[dict[str, Any]]:
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(self.line_url) as response:
                response.raise_for_status()
                return await response.json()

    async def collect(self) -> list[OddsSelection]:
        payload = await self.fetch_raw()
        return self._normalize(payload)

    def _normalize(self, payload: dict[str, Any] | list[dict[str, Any]]) -> list[OddsSelection]:
        # TODO: map real OLIMP public line schema to normalized selections.
        # Expected future flow:
        # 1. parse public events from OLIMP
        # 2. filter by self.sport
        # 3. flatten supported markets
        # 4. normalize market names for the signal engine
        if isinstance(payload, list):
            items = payload
        else:
            items = payload.get("events", []) if isinstance(payload, dict) else []

        selections: list[OddsSelection] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # Placeholder mapping for future public-feed integration.
            if {"league", "match_name", "market", "odds"} - item.keys():
                continue
            selections.append(
                OddsSelection(
                    sport=str(item.get("sport", self.sport)),
                    league=str(item["league"]),
                    match_name=str(item["match_name"]),
                    home_team=str(item.get("home_team", "")),
                    away_team=str(item.get("away_team", "")),
                    market=str(item["market"]),
                    bookmaker_name="OLIMP",
                    odds=float(item["odds"]),
                    source_event_id=str(item.get("event_id")) if item.get("event_id") is not None else None,
                    source_market_id=str(item.get("market_id")) if item.get("market_id") is not None else None,
                    raw_payload=item,
                )
            )
        return selections


async def collect_odds() -> list[dict]:
    # TODO: wire this to Settings and the signal pipeline once the real public OLIMP endpoint is fixed in env.
    return []
