import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
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
    market_group: str | None = None
    event_start_time: datetime | None = None
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
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(self.line_url, headers={"Accept": "application/json"}) as response:
                        response.raise_for_status()
                        return await response.json()
            except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("OLIMP fetch failed without a captured error.")

    async def collect(self) -> list[OddsSelection]:
        payload = await self.fetch_raw()
        return self._normalize(payload)

    def _normalize(self, payload: dict[str, Any] | list[dict[str, Any]]) -> list[OddsSelection]:
        selections: list[OddsSelection] = []
        blocks = payload if isinstance(payload, list) else [payload]

        for block in blocks:
            if not isinstance(block, dict):
                continue
            competitions = block.get("payload", {}).get("competitionsWithEvents", [])
            if not isinstance(competitions, list):
                continue
            for competition in competitions:
                if not isinstance(competition, dict):
                    continue
                events = competition.get("events", [])
                if not isinstance(events, list):
                    continue
                for event in events:
                    if not isinstance(event, dict) or not self._matches_sport(event):
                        continue
                    selections.extend(self._normalize_event(event))
        return selections

    def _normalize_event(self, event: dict[str, Any]) -> list[OddsSelection]:
        event_id = self._as_str(event.get("id"))
        league = self._as_str(event.get("competitionName"))
        match_name = self._as_str(event.get("name"))
        home_team = self._as_str(event.get("team1Name")) or ""
        away_team = self._as_str(event.get("team2Name")) or ""
        sport_name = self._as_str(event.get("sportName")) or self.sport
        event_start_time = self._parse_timestamp(event.get("startDateTime"))

        if not league or not match_name:
            return []

        selections: list[OddsSelection] = []
        outcomes = event.get("outcomes", [])
        if not isinstance(outcomes, list):
            return selections

        for outcome in outcomes:
            if not isinstance(outcome, dict) or not self._is_supported_outcome(outcome):
                continue
            odds = self._parse_float(outcome.get("probability"))
            if odds is None:
                continue
            selections.append(
                OddsSelection(
                    sport=sport_name,
                    league=league,
                    match_name=match_name,
                    home_team=home_team,
                    away_team=away_team,
                    market=self._market_name(outcome),
                    bookmaker_name="OLIMP",
                    odds=odds,
                    market_group=self._as_str(outcome.get("groupName")),
                    event_start_time=event_start_time,
                    source_event_id=event_id,
                    source_market_id=self._as_str(outcome.get("marketId")),
                    raw_payload=outcome,
                )
            )
        return selections

    def _matches_sport(self, event: dict[str, Any]) -> bool:
        target_sport = (self.sport or "").strip().lower()
        if not target_sport:
            return True

        sport_id = self._as_str(event.get("sportId"))
        if target_sport in {"football", "soccer"} and sport_id == "1":
            return True

        sport_name = (self._as_str(event.get("sportName")) or "").strip().lower()
        aliases = {
            "football": {"football", "soccer"},
            "soccer": {"football", "soccer"},
        }
        return sport_name in aliases.get(target_sport, {target_sport})

    @staticmethod
    def _is_supported_outcome(outcome: dict[str, Any]) -> bool:
        categories = {str(item).upper() for item in outcome.get("categories", [])}
        if "RESULT" in categories or "TOTAL" in categories:
            return True
        market_name = str(
            outcome.get("shortName") or outcome.get("unprocessedName") or outcome.get("groupName") or ""
        ).lower()
        compact_name = market_name.replace(" ", "")
        return "обезабьют" in compact_name or compact_name.startswith("оз") or "bothteamstoscore" in compact_name

    @staticmethod
    def _market_name(outcome: dict[str, Any]) -> str:
        return str(outcome.get("shortName") or outcome.get("unprocessedName") or outcome.get("groupName") or "Unknown")

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None
        if timestamp > 10_000_000_000:
            timestamp = timestamp // 1000
        return datetime.fromtimestamp(timestamp, tz=UTC)

    @staticmethod
    def _parse_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", "."))
        except ValueError:
            return None

    @staticmethod
    def _as_str(value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value)


async def collect_odds() -> list[dict]:
    # TODO: wire this to Settings and the signal pipeline once the real public OLIMP endpoint is used in production.
    return []
