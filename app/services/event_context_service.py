from __future__ import annotations

from dataclasses import dataclass, field

from app.collectors.api_football_collector import ApiFootballCollector, ApiFootballFixtureContext
from app.collectors.odds_collector import OddsSelection
from app.collectors.stats_collector import FootballDataStatsCollector, MatchTrendSnapshot
from app.collectors.thesportsdb_collector import TheSportsDBCollector, TheSportsDBEventContext
from app.config import Settings


@dataclass(slots=True)
class AggregatedEventContext:
    event_key: str
    home_team_name: str
    away_team_name: str
    league_name: str
    kickoff_at: object | None
    primary_source: str
    sources: list[str] = field(default_factory=list)
    trend_snapshot: MatchTrendSnapshot | None = None
    api_football_context: ApiFootballFixtureContext | None = None
    thesportsdb_context: TheSportsDBEventContext | None = None

    @property
    def official_home_name(self) -> str:
        if self.api_football_context is not None:
            return self.api_football_context.home_team_name
        if self.thesportsdb_context is not None:
            return self.thesportsdb_context.home_team_name
        return self.home_team_name

    @property
    def official_away_name(self) -> str:
        if self.api_football_context is not None:
            return self.api_football_context.away_team_name
        if self.thesportsdb_context is not None:
            return self.thesportsdb_context.away_team_name
        return self.away_team_name


class EventContextService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stats_collector = FootballDataStatsCollector(settings)
        self.api_football_collector = ApiFootballCollector(settings)
        self.thesportsdb_collector = TheSportsDBCollector(settings)

    async def build_context_lookup(self, selections: list[OddsSelection]) -> dict[str, AggregatedEventContext]:
        if not selections:
            return {}

        trend_lookup = await self._build_trend_lookup(selections)
        api_football_lookup = await self._build_api_football_lookup(selections)
        thesportsdb_lookup = await self._build_thesportsdb_lookup(selections)

        lookup: dict[str, AggregatedEventContext] = {}
        for selection in selections:
            event_key = selection.source_event_id or selection.match_name.lower()
            if event_key in lookup:
                continue

            api_context = api_football_lookup.get(event_key)
            thesportsdb_context = thesportsdb_lookup.get(event_key)
            trend_snapshot = trend_lookup.get(event_key)

            sources: list[str] = []
            primary_source = "line"
            if api_context is not None:
                primary_source = "api-football"
                sources.append("api-football")
            if thesportsdb_context is not None:
                if primary_source == "line":
                    primary_source = "thesportsdb"
                sources.append("thesportsdb")
            if trend_snapshot is not None:
                sources.append("football-data")
            if not sources:
                sources.append("line")

            lookup[event_key] = AggregatedEventContext(
                event_key=event_key,
                home_team_name=selection.home_team,
                away_team_name=selection.away_team,
                league_name=selection.league,
                kickoff_at=selection.event_start_time,
                primary_source=primary_source,
                sources=sources,
                trend_snapshot=trend_snapshot,
                api_football_context=api_context,
                thesportsdb_context=thesportsdb_context,
            )
        return lookup

    async def _build_trend_lookup(self, selections: list[OddsSelection]) -> dict[str, MatchTrendSnapshot]:
        if not self.stats_collector.is_configured:
            return {}
        try:
            return await self.stats_collector.build_trend_lookup(selections)
        except Exception:
            return {}

    async def _build_api_football_lookup(self, selections: list[OddsSelection]) -> dict[str, ApiFootballFixtureContext]:
        if not self.api_football_collector.is_configured:
            return {}
        try:
            return await self.api_football_collector.build_fixture_lookup(selections)
        except Exception:
            return {}

    async def _build_thesportsdb_lookup(self, selections: list[OddsSelection]) -> dict[str, TheSportsDBEventContext]:
        if not self.thesportsdb_collector.is_configured:
            return {}
        try:
            return await self.thesportsdb_collector.build_event_lookup(selections)
        except Exception:
            return {}
