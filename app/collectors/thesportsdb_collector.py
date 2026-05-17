from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import aiohttp

from app.collectors.api_football_collector import _name_similarity
from app.collectors.news_collector import GNewsCollector
from app.collectors.odds_collector import OddsSelection
from app.config import Settings
from app.services.health_status_service import HealthStatusService
from app.services.provider_state import update_provider_status


_EVENT_CACHE: dict[str, tuple[datetime, "TheSportsDBEventContext | None"]] = {}
_TEAM_CACHE: dict[str, tuple[datetime, str | None]] = {}


@dataclass(slots=True)
class TheSportsDBEventContext:
    event_id: str | None
    event_name: str
    league_name: str | None
    kickoff_at: datetime | None
    home_team_name: str
    away_team_name: str


class TheSportsDBCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.health_status = HealthStatusService()

    @property
    def resolved_api_key(self) -> str | None:
        raw = self.settings.thesportsdb_api_key
        if raw in (None, ""):
            return "123"
        return _extract_api_key(raw)

    @property
    def is_configured(self) -> bool:
        return self.settings.thesportsdb_enabled and bool(self.resolved_api_key)

    async def build_event_lookup(self, selections: list[OddsSelection]) -> dict[str, TheSportsDBEventContext]:
        if not selections:
            return {}
        if not self.is_configured:
            snapshot = update_provider_status(
                "thesportsdb",
                enabled=self.settings.thesportsdb_enabled,
                configured=bool(self.resolved_api_key),
                last_status="disabled" if not self.settings.thesportsdb_enabled else "misconfigured",
                last_message="TheSportsDB выключен или без рабочего API key.",
            )
            await self.health_status.persist_provider_status(snapshot)
            return {}

        snapshot = update_provider_status(
            "thesportsdb",
            enabled=True,
            configured=True,
            last_attempt_at=datetime.now(UTC),
            last_status="running",
            last_message="Запрос fallback-контекста TheSportsDB...",
            last_error=None,
            cache_hit=False,
        )
        await self.health_status.persist_provider_status(snapshot)

        lookup: dict[str, TheSportsDBEventContext] = {}
        cache_hits = 0
        for selection in selections:
            event_key = selection.source_event_id or selection.match_name.lower()
            if event_key in lookup:
                continue
            context, used_cache = await self.lookup_event_context(selection)
            if used_cache:
                cache_hits += 1
            if context is not None:
                lookup[event_key] = context

        snapshot = update_provider_status(
            "thesportsdb",
            enabled=True,
            configured=True,
            last_success_at=datetime.now(UTC),
            last_status="success",
            last_message="TheSportsDB fallback-контекст обновлён.",
            items_count=len(lookup),
            cache_hit=cache_hits > 0,
            last_error=None,
        )
        await self.health_status.persist_provider_status(snapshot)
        return lookup

    async def lookup_event_context(self, selection: OddsSelection) -> tuple[TheSportsDBEventContext | None, bool]:
        cache_key = self._cache_key(selection)
        now = datetime.now(UTC)
        cache_ttl = timedelta(minutes=max(self.settings.thesportsdb_cache_minutes, 1))

        cached = _EVENT_CACHE.get(cache_key)
        if cached and now - cached[0] <= cache_ttl:
            snapshot = update_provider_status(
                "thesportsdb",
                enabled=True,
                configured=True,
                last_attempt_at=now,
                last_success_at=now,
                last_status="success",
                last_message="TheSportsDB отдал fallback-контекст из кэша." if cached[1] else "TheSportsDB отдал miss из кэша.",
                items_count=1 if cached[1] is not None else 0,
                cache_hit=True,
                last_error=None,
            )
            await self.health_status.persist_provider_status(snapshot)
            return cached[1], True

        try:
            context = await self._fetch_event_context(selection)
        except Exception as exc:
            snapshot = update_provider_status(
                "thesportsdb",
                enabled=True,
                configured=True,
                last_status="error",
                last_message="Ошибка запроса TheSportsDB.",
                last_error=str(exc),
            )
            await self.health_status.persist_provider_status(snapshot)
            raise

        _EVENT_CACHE[cache_key] = (now, context)
        snapshot = update_provider_status(
            "thesportsdb",
            enabled=True,
            configured=True,
            last_attempt_at=now,
            last_success_at=now,
            last_status="success",
            last_message="TheSportsDB нашёл fallback-контекст." if context is not None else "TheSportsDB не нашёл match для события.",
            items_count=1 if context is not None else 0,
            cache_hit=False,
            last_error=None,
        )
        await self.health_status.persist_provider_status(snapshot)
        return context, False

    async def _fetch_event_context(self, selection: OddsSelection) -> TheSportsDBEventContext | None:
        if selection.event_start_time is None:
            return None

        queries = self._build_event_queries(selection)
        timeout = aiohttp.ClientTimeout(total=self.settings.olimp_timeout_seconds)
        endpoint = self._build_endpoint("searchevents.php")

        async with aiohttp.ClientSession(timeout=timeout, headers={"Accept": "application/json"}) as session:
            for query in queries:
                params = {
                    "e": query,
                    "s": "Soccer",
                    "d": selection.event_start_time.astimezone(UTC).date().isoformat(),
                }
                async with session.get(endpoint, params=params) as response:
                    response.raise_for_status()
                    payload = await response.json()
                context = self._best_event_match(selection, payload)
                if context is not None:
                    return context

            home_name = await self._lookup_team_name(session, selection.home_team)
            away_name = await self._lookup_team_name(session, selection.away_team)
            if home_name or away_name:
                return TheSportsDBEventContext(
                    event_id=None,
                    event_name=selection.match_name,
                    league_name=selection.league,
                    kickoff_at=selection.event_start_time,
                    home_team_name=home_name or selection.home_team,
                    away_team_name=away_name or selection.away_team,
                )
        return None

    async def _lookup_team_name(self, session: aiohttp.ClientSession, team_name: str) -> str | None:
        normalized = team_name.strip().lower()
        now = datetime.now(UTC)
        cache_ttl = timedelta(minutes=max(self.settings.thesportsdb_cache_minutes, 1))
        cached = _TEAM_CACHE.get(normalized)
        if cached and now - cached[0] <= cache_ttl:
            return cached[1]

        endpoint = self._build_endpoint("searchteams.php")
        best_name: str | None = None
        best_score = 0.0
        for variant in GNewsCollector._team_variants(team_name):
            if not _looks_latin(variant):
                continue
            async with session.get(endpoint, params={"t": variant}) as response:
                response.raise_for_status()
                payload = await response.json()
            items = payload.get("teams", []) if isinstance(payload, dict) else []
            for item in items:
                candidate_name = str((item or {}).get("strTeam") or "").strip()
                if not candidate_name:
                    continue
                score = _name_similarity(team_name, candidate_name)
                if score > best_score:
                    best_score = score
                    best_name = candidate_name
            if best_score >= 0.92:
                break

        if best_score < 0.78:
            best_name = None
        _TEAM_CACHE[normalized] = (now, best_name)
        return best_name

    def _best_event_match(self, selection: OddsSelection, payload: dict[str, Any]) -> TheSportsDBEventContext | None:
        items = []
        if isinstance(payload, dict):
            raw_items = payload.get("event") or payload.get("events") or []
            if isinstance(raw_items, list):
                items = raw_items

        best_score = 0.0
        best_context: TheSportsDBEventContext | None = None
        for item in items:
            if not isinstance(item, dict):
                continue
            home_name = str(item.get("strHomeTeam") or "").strip()
            away_name = str(item.get("strAwayTeam") or "").strip()
            if not home_name or not away_name:
                continue

            league_name = str(item.get("strLeague") or item.get("strLeagueAlternate") or "").strip() or None
            event_name = str(item.get("strEvent") or f"{home_name} vs {away_name}").strip()
            kickoff_at = _parse_event_datetime(item.get("dateEvent"), item.get("strTime"))

            score = self._event_match_score(selection, home_name, away_name, league_name)
            if score > best_score:
                best_score = score
                best_context = TheSportsDBEventContext(
                    event_id=str(item.get("idEvent") or "").strip() or None,
                    event_name=event_name,
                    league_name=league_name,
                    kickoff_at=kickoff_at,
                    home_team_name=home_name,
                    away_team_name=away_name,
                )

        if best_score < 0.74:
            return None
        return best_context

    def _event_match_score(
        self,
        selection: OddsSelection,
        home_name: str,
        away_name: str,
        league_name: str | None,
    ) -> float:
        same_order = (_name_similarity(selection.home_team, home_name) + _name_similarity(selection.away_team, away_name)) / 2
        swapped_order = (_name_similarity(selection.home_team, away_name) + _name_similarity(selection.away_team, home_name)) / 2
        team_score = max(same_order, swapped_order)
        league_score = _name_similarity(selection.league, league_name or selection.league)
        return team_score * 0.9 + league_score * 0.1

    def _build_endpoint(self, path: str) -> str:
        api_key = self.resolved_api_key or "123"
        return f"{self.settings.thesportsdb_base_url.rstrip('/')}/{api_key}/{path}"

    @staticmethod
    def _cache_key(selection: OddsSelection) -> str:
        kickoff = selection.event_start_time.astimezone(UTC).isoformat() if selection.event_start_time else ""
        return "|".join([selection.home_team.lower(), selection.away_team.lower(), selection.league.lower(), kickoff])

    @staticmethod
    def _build_event_queries(selection: OddsSelection) -> list[str]:
        home_variants = [variant for variant in GNewsCollector._team_variants(selection.home_team) if _looks_latin(variant)]
        away_variants = [variant for variant in GNewsCollector._team_variants(selection.away_team) if _looks_latin(variant)]
        queries: list[str] = []
        for home in home_variants[:3]:
            for away in away_variants[:3]:
                for separator in (" vs ", " v "):
                    query = f"{home}{separator}{away}"
                    if query not in queries and len(query) <= 80:
                        queries.append(query)
        if not queries:
            queries.append(f"{selection.home_team} vs {selection.away_team}")
        return queries


def _extract_api_key(raw: str) -> str | None:
    text = str(raw).strip()
    if not text:
        return None

    url_match = re.search(r"/json/([^/]+)/", text)
    if url_match:
        return url_match.group(1).strip()

    if text.startswith("{") or text.startswith("["):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        candidate = _search_json_for_key(payload)
        if candidate:
            return candidate

    return text


def _search_json_for_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("api_key", "apikey", "key", "id", "v1_key", "v1Key"):
            direct = value.get(key)
            if isinstance(direct, (str, int, float)) and str(direct).strip():
                return str(direct).strip()
        for nested in value.values():
            found = _search_json_for_key(nested)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _search_json_for_key(item)
            if found:
                return found
    elif isinstance(value, (str, int, float)):
        text = str(value).strip()
        if text and len(text) <= 128:
            return text
    return None


def _parse_event_datetime(date_value: Any, time_value: Any) -> datetime | None:
    if date_value in (None, ""):
        return None
    date_text = str(date_value).strip()
    time_text = str(time_value or "00:00:00").strip()
    if not time_text:
        time_text = "00:00:00"
    if len(time_text) == 5:
        time_text = f"{time_text}:00"
    try:
        return datetime.fromisoformat(f"{date_text}T{time_text}+00:00").astimezone(UTC)
    except ValueError:
        return None


def _looks_latin(value: str) -> bool:
    return any("a" <= ch.lower() <= "z" for ch in value)
