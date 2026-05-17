from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

import aiohttp

from app.collectors.odds_collector import OddsSelection
from app.config import Settings
from app.services.health_status_service import HealthStatusService
from app.services.provider_state import update_provider_status


CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)

NAME_STOPWORDS = {
    "fc",
    "fk",
    "sc",
    "cf",
    "club",
    "afc",
    "pfc",
    "women",
    "woman",
    "ladies",
    "reserves",
    "reserve",
    "youth",
    "u17",
    "u18",
    "u19",
    "u20",
    "u21",
    "do17",
    "do18",
    "do19",
    "do20",
    "do21",
}

_FIXTURES_CACHE: dict[str, tuple[datetime, list["ApiFootballFixtureContext"]]] = {}
_LINEUPS_CACHE: dict[int, tuple[datetime, dict[str, Any]]] = {}
_INJURIES_CACHE: dict[int, tuple[datetime, dict[str, Any]]] = {}


@dataclass(slots=True)
class ApiFootballFixtureContext:
    fixture_id: int
    league_name: str
    country_name: str | None
    kickoff_at: datetime | None
    home_team_name: str
    away_team_name: str
    venue_name: str | None = None
    home_injuries: int = 0
    away_injuries: int = 0
    lineups_confirmed: bool = False
    home_coach: str | None = None
    away_coach: str | None = None
    status_short: str | None = None
    status_long: str | None = None
    fulltime_home_goals: int | None = None
    fulltime_away_goals: int | None = None


class ApiFootballCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.health_status = HealthStatusService()

    @property
    def is_configured(self) -> bool:
        return self.settings.api_football_enabled and bool(self.settings.api_football_api_key)

    async def build_fixture_lookup(self, selections: list[OddsSelection]) -> dict[str, ApiFootballFixtureContext]:
        if not self.is_configured or not selections:
            snapshot = update_provider_status(
                "api-football",
                enabled=self.settings.api_football_enabled,
                configured=bool(self.settings.api_football_api_key),
                last_status="disabled" if not self.settings.api_football_enabled else "misconfigured",
                last_message="API-FOOTBALL не включен или без ключа.",
            )
            await self.health_status.persist_provider_status(snapshot)
            return {}

        dates = sorted(
            {
                selection.event_start_time.astimezone(UTC).date()
                for selection in selections
                if selection.event_start_time is not None
            }
        )
        try:
            fixtures_by_date = await self.fetch_fixtures_for_dates(dates)
        except Exception as exc:
            snapshot = update_provider_status(
                "api-football",
                enabled=True,
                configured=True,
                last_status="error",
                last_message="Ошибка запроса API-FOOTBALL.",
                last_error=str(exc),
            )
            await self.health_status.persist_provider_status(snapshot)
            raise

        lookup: dict[str, ApiFootballFixtureContext] = {}
        for selection in selections:
            event_key = selection.source_event_id or selection.match_name.lower()
            if event_key in lookup:
                continue
            fixture = self.match_selection(selection, fixtures_by_date)
            if fixture is None:
                continue
            if self._should_enrich_fixture(selection):
                await self._enrich_fixture(fixture)
            lookup[event_key] = fixture
        return lookup

    async def build_signal_fixture_lookup(self, signals: list[Any]) -> dict[int, ApiFootballFixtureContext]:
        if not self.is_configured or not signals:
            return {}

        dates = sorted(
            {
                signal.match_start_time.astimezone(UTC).date() + timedelta(days=offset)
                for signal in signals
                if signal.match_start_time is not None
                for offset in (-1, 0, 1)
            }
        )
        fixtures_by_date = await self.fetch_fixtures_for_dates(dates)
        lookup: dict[int, ApiFootballFixtureContext] = {}
        for signal in signals:
            fixture = self.match_signal(signal, fixtures_by_date)
            if fixture is not None:
                lookup[signal.id] = fixture
        return lookup

    async def fetch_fixtures_for_dates(self, dates: list[date]) -> dict[date, list[ApiFootballFixtureContext]]:
        if not dates or not self.is_configured:
            return {}

        now = datetime.now(UTC)
        cache_ttl = timedelta(minutes=max(self.settings.api_football_cache_minutes, 1))
        headers = {
            "x-apisports-key": self.settings.api_football_api_key or "",
            "Accept": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=self.settings.olimp_timeout_seconds)
        fixtures_by_date: dict[date, list[ApiFootballFixtureContext]] = {}

        snapshot = update_provider_status(
            "api-football",
            enabled=True,
            configured=True,
            last_attempt_at=datetime.now(UTC),
            last_status="running",
            last_message="Запрос fixtures API-FOOTBALL...",
            last_error=None,
            cache_hit=False,
        )
        await self.health_status.persist_provider_status(snapshot)

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for target_date in dates:
                cache_key = target_date.isoformat()
                cached = _FIXTURES_CACHE.get(cache_key)
                if cached and now - cached[0] <= cache_ttl:
                    fixtures_by_date[target_date] = cached[1]
                    snapshot = update_provider_status(
                        "api-football",
                        enabled=True,
                        configured=True,
                        last_status="success",
                        last_message="API-FOOTBALL отдал fixtures из кэша.",
                        cache_hit=True,
                        items_count=sum(len(items) for items in fixtures_by_date.values()),
                    )
                    await self.health_status.persist_provider_status(snapshot)
                    continue

                url = f"{self.settings.api_football_base_url.rstrip('/')}/fixtures"
                async with session.get(url, params={"date": target_date.isoformat()}) as response:
                    response.raise_for_status()
                    payload = await response.json()
                contexts = self._parse_fixture_response(payload)
                _FIXTURES_CACHE[cache_key] = (now, contexts)
                fixtures_by_date[target_date] = contexts

        snapshot = update_provider_status(
            "api-football",
            enabled=True,
            configured=True,
            last_success_at=datetime.now(UTC),
            last_status="success",
            last_message="Fixtures API-FOOTBALL обновлены.",
            items_count=sum(len(items) for items in fixtures_by_date.values()),
            cache_hit=False,
            last_error=None,
        )
        await self.health_status.persist_provider_status(snapshot)
        return fixtures_by_date

    def match_selection(
        self,
        selection: OddsSelection,
        fixtures_by_date: dict[date, list[ApiFootballFixtureContext]],
    ) -> ApiFootballFixtureContext | None:
        if selection.event_start_time is None:
            return None

        target_date = selection.event_start_time.astimezone(UTC).date()
        candidates = fixtures_by_date.get(target_date, [])
        if not candidates:
            return None

        best_score = 0.0
        best_fixture: ApiFootballFixtureContext | None = None
        for fixture in candidates:
            score = self._match_score(selection, fixture)
            if score > best_score:
                best_score = score
                best_fixture = fixture
        if best_score < 0.76:
            return None
        return best_fixture

    def match_signal(
        self,
        signal: Any,
        fixtures_by_date: dict[date, list[ApiFootballFixtureContext]],
    ) -> ApiFootballFixtureContext | None:
        if signal.match_start_time is None:
            return None

        target_date = signal.match_start_time.astimezone(UTC).date()
        candidates = (
            fixtures_by_date.get(target_date, [])
            + fixtures_by_date.get(target_date - timedelta(days=1), [])
            + fixtures_by_date.get(target_date + timedelta(days=1), [])
        )
        if not candidates:
            return None

        best_score = 0.0
        best_fixture: ApiFootballFixtureContext | None = None
        for fixture in candidates:
            score = self._signal_match_score(signal, fixture)
            if score > best_score:
                best_score = score
                best_fixture = fixture
        if best_score < 0.76:
            return None
        return best_fixture

    async def _enrich_fixture(self, fixture: ApiFootballFixtureContext) -> None:
        lineups_payload = await self._fetch_lineups_payload(fixture.fixture_id)
        injuries_payload = await self._fetch_injuries_payload(fixture.fixture_id)

        if lineups_payload:
            fixture.lineups_confirmed = len(lineups_payload.get("response", [])) >= 2
            participants = lineups_payload.get("response", [])
            if isinstance(participants, list):
                for item in participants:
                    team_name = str(((item or {}).get("team") or {}).get("name") or "").strip()
                    coach_name = str(((item or {}).get("coach") or {}).get("name") or "").strip() or None
                    if _name_similarity(team_name, fixture.home_team_name) >= 0.84:
                        fixture.home_coach = coach_name
                    elif _name_similarity(team_name, fixture.away_team_name) >= 0.84:
                        fixture.away_coach = coach_name

        if injuries_payload:
            participants = injuries_payload.get("response", [])
            if isinstance(participants, list):
                home_count = 0
                away_count = 0
                for item in participants:
                    team_name = str(((item or {}).get("team") or {}).get("name") or "").strip()
                    if _name_similarity(team_name, fixture.home_team_name) >= 0.84:
                        home_count += 1
                    elif _name_similarity(team_name, fixture.away_team_name) >= 0.84:
                        away_count += 1
                fixture.home_injuries = home_count
                fixture.away_injuries = away_count

    async def _fetch_lineups_payload(self, fixture_id: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        cache_ttl = timedelta(minutes=max(self.settings.api_football_cache_minutes, 1))
        cached = _LINEUPS_CACHE.get(fixture_id)
        if cached and now - cached[0] <= cache_ttl:
            return cached[1]

        payload = await self._request_json("fixtures/lineups", {"fixture": str(fixture_id)})
        _LINEUPS_CACHE[fixture_id] = (now, payload)
        return payload

    async def _fetch_injuries_payload(self, fixture_id: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        cache_ttl = timedelta(minutes=max(self.settings.api_football_cache_minutes, 1))
        cached = _INJURIES_CACHE.get(fixture_id)
        if cached and now - cached[0] <= cache_ttl:
            return cached[1]

        payload = await self._request_json("injuries", {"fixture": str(fixture_id)})
        _INJURIES_CACHE[fixture_id] = (now, payload)
        return payload

    async def _request_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        headers = {
            "x-apisports-key": self.settings.api_football_api_key or "",
            "Accept": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=self.settings.olimp_timeout_seconds)
        url = f"{self.settings.api_football_base_url.rstrip('/')}/{path.lstrip('/')}"
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                payload = await response.json()
        return payload if isinstance(payload, dict) else {}

    def _parse_fixture_response(self, payload: dict[str, Any]) -> list[ApiFootballFixtureContext]:
        items = payload.get("response", []) if isinstance(payload, dict) else []
        contexts: list[ApiFootballFixtureContext] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            fixture = item.get("fixture") or {}
            league = item.get("league") or {}
            teams = item.get("teams") or {}
            home = teams.get("home") or {}
            away = teams.get("away") or {}
            home_name = str(home.get("name") or "").strip()
            away_name = str(away.get("name") or "").strip()
            if not home_name or not away_name:
                continue
            contexts.append(
                ApiFootballFixtureContext(
                    fixture_id=int(fixture.get("id") or 0),
                    league_name=str(league.get("name") or "").strip(),
                    country_name=str(league.get("country") or "").strip() or None,
                    kickoff_at=_parse_iso_datetime(fixture.get("date")),
                    home_team_name=home_name,
                    away_team_name=away_name,
                    venue_name=str((fixture.get("venue") or {}).get("name") or "").strip() or None,
                    status_short=str(((fixture.get("status") or {}).get("short")) or "").strip() or None,
                    status_long=str(((fixture.get("status") or {}).get("long")) or "").strip() or None,
                    fulltime_home_goals=_as_int(((item.get("score") or {}).get("fulltime") or {}).get("home")),
                    fulltime_away_goals=_as_int(((item.get("score") or {}).get("fulltime") or {}).get("away")),
                )
            )
        return contexts

    def _should_enrich_fixture(self, selection: OddsSelection) -> bool:
        if selection.event_start_time is None:
            return False
        minutes_to_start = (selection.event_start_time.astimezone(UTC) - datetime.now(UTC)).total_seconds() / 60
        return 0 <= minutes_to_start <= max(self.settings.api_football_close_window_minutes, 1)

    def _match_score(self, selection: OddsSelection, fixture: ApiFootballFixtureContext) -> float:
        home_same = _name_similarity(selection.home_team, fixture.home_team_name)
        away_same = _name_similarity(selection.away_team, fixture.away_team_name)
        same_order = (home_same + away_same) / 2

        home_swapped = _name_similarity(selection.home_team, fixture.away_team_name)
        away_swapped = _name_similarity(selection.away_team, fixture.home_team_name)
        swapped_order = (home_swapped + away_swapped) / 2

        team_score = max(same_order, swapped_order)
        league_name = fixture.league_name
        if fixture.country_name:
            league_name = f"{fixture.country_name}. {fixture.league_name}"
        league_score = _name_similarity(selection.league, league_name)
        return team_score * 0.88 + league_score * 0.12

    def _signal_match_score(self, signal: Any, fixture: ApiFootballFixtureContext) -> float:
        home_same = _name_similarity(signal.home_team, fixture.home_team_name)
        away_same = _name_similarity(signal.away_team, fixture.away_team_name)
        same_order = (home_same + away_same) / 2

        home_swapped = _name_similarity(signal.home_team, fixture.away_team_name)
        away_swapped = _name_similarity(signal.away_team, fixture.home_team_name)
        swapped_order = (home_swapped + away_swapped) / 2

        team_score = max(same_order, swapped_order)
        league_name = fixture.league_name
        if fixture.country_name:
            league_name = f"{fixture.country_name}. {fixture.league_name}"
        league_score = _name_similarity(signal.league, league_name)
        return team_score * 0.88 + league_score * 0.12


def _normalize_name(value: str) -> str:
    text = value.lower().translate(CYRILLIC_TO_LATIN)
    sanitized = "".join(char if char.isalnum() else " " for char in text)
    tokens = [token for token in sanitized.split() if token and token not in NAME_STOPWORDS]
    return " ".join(tokens)


def _name_similarity(left: str, right: str) -> float:
    left_norm = _normalize_name(left)
    right_norm = _normalize_name(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0

    ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    token_score = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    substring_score = 1.0 if left_norm in right_norm or right_norm in left_norm else 0.0
    return max(ratio, token_score, substring_score * 0.95)


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
