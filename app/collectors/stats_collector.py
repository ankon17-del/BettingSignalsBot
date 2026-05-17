from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from typing import Any

import aiohttp

from app.collectors.odds_collector import OddsSelection
from app.config import Settings


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


@dataclass(slots=True)
class TeamTrendSnapshot:
    team_id: int | None
    team_name: str
    avg_goals: float | None
    avg_goals_conceded: float | None
    avg_goals_scored: float | None
    avg_points: float | None
    pct_bts: float | None
    pct_draws: float | None
    pct_losses: float | None
    pct_o_25: float | None
    pct_u_25: float | None
    pct_wins: float | None
    form: str | None


@dataclass(slots=True)
class MatchTrendSnapshot:
    match_id: int
    competition_name: str
    utc_date: datetime | None
    home_team: TeamTrendSnapshot
    away_team: TeamTrendSnapshot


class FootballDataStatsCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return self.settings.football_data_enabled and bool(self.settings.football_data_api_token)

    async def build_trend_lookup(self, selections: list[OddsSelection]) -> dict[str, MatchTrendSnapshot]:
        if not self.is_configured:
            return {}

        dates = sorted(
            {
                selection.event_start_time.astimezone(UTC).date()
                for selection in selections
                if selection.event_start_time is not None
            }
        )
        if not dates:
            return {}

        snapshots_by_date = await self.fetch_trends_for_dates(dates)
        lookup: dict[str, MatchTrendSnapshot] = {}
        for selection in selections:
            event_key = selection.source_event_id or selection.match_name.lower()
            if event_key in lookup:
                continue
            snapshot = self.match_selection(selection, snapshots_by_date)
            if snapshot is not None:
                lookup[event_key] = snapshot
        return lookup

    async def fetch_trends_for_dates(self, dates: list[date]) -> dict[date, list[MatchTrendSnapshot]]:
        if not dates or not self.is_configured:
            return {}

        timeout = aiohttp.ClientTimeout(total=self.settings.olimp_timeout_seconds)
        headers = {
            "X-Auth-Token": self.settings.football_data_api_token or "",
            "Accept": "application/json",
        }
        snapshots_by_date: dict[date, list[MatchTrendSnapshot]] = {}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for target_date in dates:
                params = {
                    "date": target_date.isoformat(),
                    "window": str(self.settings.football_data_trend_window),
                }
                if self.settings.football_data_consider_side:
                    params["consider_side"] = "true"

                url = f"{self.settings.football_data_base_url.rstrip('/')}/trends/"
                async with session.get(url, params=params) as response:
                    response.raise_for_status()
                    payload = await response.json()
                trend_items = payload.get("trends", []) if isinstance(payload, dict) else []
                snapshots_by_date[target_date] = [
                    snapshot
                    for item in trend_items
                    if isinstance(item, dict) and (snapshot := self._parse_match_snapshot(item)) is not None
                ]
        return snapshots_by_date

    def match_selection(
        self,
        selection: OddsSelection,
        snapshots_by_date: dict[date, list[MatchTrendSnapshot]],
    ) -> MatchTrendSnapshot | None:
        if selection.event_start_time is None:
            return None

        target_date = selection.event_start_time.astimezone(UTC).date()
        candidates = snapshots_by_date.get(target_date, [])
        if not candidates:
            return None

        best_score = 0.0
        best_snapshot: MatchTrendSnapshot | None = None
        for snapshot in candidates:
            score = self._match_score(selection, snapshot)
            if score > best_score:
                best_score = score
                best_snapshot = snapshot

        if best_score < self.settings.football_data_name_similarity:
            return None
        return best_snapshot

    def _match_score(self, selection: OddsSelection, snapshot: MatchTrendSnapshot) -> float:
        home_same = _name_similarity(selection.home_team, snapshot.home_team.team_name)
        away_same = _name_similarity(selection.away_team, snapshot.away_team.team_name)
        same_order = (home_same + away_same) / 2

        home_swapped = _name_similarity(selection.home_team, snapshot.away_team.team_name)
        away_swapped = _name_similarity(selection.away_team, snapshot.home_team.team_name)
        swapped_order = (home_swapped + away_swapped) / 2

        team_score = max(same_order, swapped_order)
        league_score = _name_similarity(selection.league, snapshot.competition_name)
        return team_score * 0.85 + league_score * 0.15

    def _parse_match_snapshot(self, item: dict[str, Any]) -> MatchTrendSnapshot | None:
        home_team = item.get("homeTeam") or {}
        away_team = item.get("awayTeam") or {}
        trend = item.get("trend") or {}
        home_trend = trend.get("home") or {}
        away_trend = trend.get("away") or {}

        home_name = str(home_team.get("name") or "").strip()
        away_name = str(away_team.get("name") or "").strip()
        competition_name = str((item.get("competition") or {}).get("name") or "").strip()
        if not home_name or not away_name:
            return None

        return MatchTrendSnapshot(
            match_id=int(item.get("id") or 0),
            competition_name=competition_name,
            utc_date=_parse_iso_datetime(item.get("utcDate")),
            home_team=_parse_team_snapshot(home_team, home_trend),
            away_team=_parse_team_snapshot(away_team, away_trend),
        )


def _parse_team_snapshot(team: dict[str, Any], trend: dict[str, Any]) -> TeamTrendSnapshot:
    return TeamTrendSnapshot(
        team_id=_parse_int(team.get("id")),
        team_name=str(team.get("name") or "").strip(),
        avg_goals=_parse_float(trend.get("avg_goals")),
        avg_goals_conceded=_parse_float(trend.get("avg_goals_conceded")),
        avg_goals_scored=_parse_float(trend.get("avg_goals_scored")),
        avg_points=_parse_float(trend.get("avg_points")),
        pct_bts=_parse_float(trend.get("pct_bts")),
        pct_draws=_parse_float(trend.get("pct_draws")),
        pct_losses=_parse_float(trend.get("pct_losses")),
        pct_o_25=_parse_float(trend.get("pct_o_25")),
        pct_u_25=_parse_float(trend.get("pct_u_25")),
        pct_wins=_parse_float(trend.get("pct_wins")),
        form=str(trend.get("form") or "").strip() or None,
    )


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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

