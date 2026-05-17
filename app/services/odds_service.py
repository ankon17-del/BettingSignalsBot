from dataclasses import dataclass
from datetime import datetime, timezone

from app.collectors.odds_collector import OddsSelection, OlimpOddsCollector
from app.config import Settings
from app.engine.value_detector import bookmaker_probability
from app.services.health_status_service import HealthStatusService
from app.services.provider_state import update_provider_status


@dataclass(slots=True)
class OlimpSignalCandidate:
    selection: OddsSelection
    bookmaker_probability: float
    candidate_tier: str
    rationale: str


@dataclass(slots=True)
class OlimpLeagueSummary:
    league: str
    matches_count: int


class OddsFeedService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.health_status = HealthStatusService()

    async def fetch_olimp_selections(self, limit: int = 12) -> list[OddsSelection]:
        if not self.settings.olimp_enabled:
            snapshot = update_provider_status(
                "olimp",
                enabled=False,
                configured=bool(self.settings.olimp_public_line_url),
                last_status="disabled",
                last_message="OLIMP feed выключен.",
            )
            await self.health_status.persist_provider_status(snapshot)
            raise ValueError("OLIMP feed is disabled in settings.")

        if not self.settings.olimp_public_line_url:
            snapshot = update_provider_status(
                "olimp",
                enabled=True,
                configured=False,
                last_status="misconfigured",
                last_message="OLIMP_PUBLIC_LINE_URL не задан.",
            )
            await self.health_status.persist_provider_status(snapshot)
            raise ValueError("OLIMP_PUBLIC_LINE_URL is not configured.")

        collector = OlimpOddsCollector(
            line_url=self.settings.olimp_public_line_url,
            timeout_seconds=self.settings.olimp_timeout_seconds,
            sport=self.settings.olimp_sport,
        )

        snapshot = update_provider_status(
            "olimp",
            enabled=True,
            configured=True,
            last_attempt_at=datetime.now(timezone.utc),
            last_status="running",
            last_message="Запрос линии OLIMP...",
            last_error=None,
        )
        await self.health_status.persist_provider_status(snapshot)

        try:
            selections = await collector.collect()
        except Exception as exc:
            snapshot = update_provider_status(
                "olimp",
                enabled=True,
                configured=True,
                last_status="error",
                last_message="Ошибка запроса линии OLIMP.",
                last_error=str(exc),
            )
            await self.health_status.persist_provider_status(snapshot)
            raise

        selections.sort(
            key=lambda item: (
                item.event_start_time.isoformat() if item.event_start_time else "",
                item.league,
                item.match_name,
                item.market,
            )
        )

        snapshot = update_provider_status(
            "olimp",
            enabled=True,
            configured=True,
            last_success_at=datetime.now(timezone.utc),
            last_status="success",
            last_message="Линия OLIMP успешно обновлена.",
            items_count=len(selections),
            cache_hit=False,
            last_error=None,
        )
        await self.health_status.persist_provider_status(snapshot)
        return selections[:limit]

    async def fetch_olimp_filtered_selections(
        self,
        match_limit: int = 5,
        markets_per_match: int = 3,
        league_filter: str | None = None,
    ) -> list[OddsSelection]:
        raw_selections = await self.fetch_olimp_selections(limit=10_000)
        normalized_league_filter = (league_filter or "").strip().lower()

        grouped: dict[str, list[OddsSelection]] = {}
        for selection in raw_selections:
            if not self._is_supported_selection_context(selection):
                continue
            normalized_market = self._normalize_market(selection)
            if normalized_market is None:
                continue
            selection.market = normalized_market
            event_key = selection.source_event_id or f"{selection.match_name}|{selection.league}"
            grouped.setdefault(event_key, [])
            if not any(existing.market == selection.market for existing in grouped[event_key]):
                grouped[event_key].append(selection)

        result: list[OddsSelection] = []
        for event_key in sorted(grouped, key=lambda key: self._event_sort_key(grouped[key][0])):
            event_selections = grouped[event_key]
            if normalized_league_filter and normalized_league_filter not in event_selections[0].league.lower():
                continue
            picked = self._pick_markets(event_selections, markets_per_match)
            if picked:
                result.extend(picked)
            if len({item.source_event_id or item.match_name for item in result}) >= match_limit:
                break
        return result

    async def fetch_olimp_candidates(
        self,
        match_limit: int = 5,
        markets_per_match: int = 3,
        league_filter: str | None = None,
    ) -> list[OlimpSignalCandidate]:
        selections = await self.fetch_olimp_filtered_selections(
            match_limit=match_limit,
            markets_per_match=markets_per_match,
            league_filter=league_filter,
        )
        candidates: list[OlimpSignalCandidate] = []
        for selection in selections:
            tier, rationale = self._classify_candidate(selection)
            candidates.append(
                OlimpSignalCandidate(
                    selection=selection,
                    bookmaker_probability=bookmaker_probability(selection.odds),
                    candidate_tier=tier,
                    rationale=rationale,
                )
            )
        return candidates

    async def fetch_olimp_leagues(self, limit: int = 20, query: str | None = None) -> list[OlimpLeagueSummary]:
        raw_selections = await self.fetch_olimp_selections(limit=10_000)
        normalized_query = (query or "").strip().lower()

        grouped: dict[str, set[str]] = {}
        for selection in raw_selections:
            if not self._is_supported_selection_context(selection):
                continue
            league = selection.league.strip()
            if not league:
                continue
            if normalized_query and normalized_query not in league.lower():
                continue
            event_key = selection.source_event_id or f"{selection.match_name}|{selection.league}"
            grouped.setdefault(league, set()).add(event_key)

        summaries = [
            OlimpLeagueSummary(league=league, matches_count=len(event_keys))
            for league, event_keys in grouped.items()
        ]
        summaries.sort(key=lambda item: (-item.matches_count, item.league))
        return summaries[:limit]

    @staticmethod
    def _normalize_market(selection: OddsSelection) -> str | None:
        raw_market = (selection.market or "").strip()
        market_map = {
            "П1": "1",
            "Х": "X",
            "П2": "2",
            "1Х": "1X",
            "12": "12",
            "Х2": "X2",
        }
        if raw_market in market_map:
            return market_map[raw_market]

        raw_payload = selection.raw_payload or {}
        short_name = str(raw_payload.get("shortName") or raw_market).strip()
        compact_short_name = short_name.lower().replace(" ", "")
        unprocessed_name = str(raw_payload.get("unprocessedName") or "").strip().lower().replace(" ", "")
        param = str(raw_payload.get("param") or "").strip()

        if param == "2.50" and short_name == "ТотБ":
            return "Over 2.5"
        if param == "2.50" and short_name == "ТотМ":
            return "Under 2.5"

        btts_haystack = f"{compact_short_name}|{unprocessed_name}"
        if "обезабьют" in btts_haystack or compact_short_name.startswith("оз") or "bothteamstoscore" in btts_haystack:
            if any(token in btts_haystack for token in {"да", "yes"}):
                return "BTTS Yes"
            if any(token in btts_haystack for token in {"нет", "no"}):
                return "BTTS No"

        return None

    @staticmethod
    def _pick_markets(selections: list[OddsSelection], markets_per_match: int) -> list[OddsSelection]:
        priority = ["1", "X", "2", "Over 2.5", "Under 2.5", "BTTS Yes", "BTTS No", "1X", "X2", "12"]
        by_market = {selection.market: selection for selection in selections}
        picked: list[OddsSelection] = []
        for market in priority:
            selection = by_market.get(market)
            if selection is not None:
                picked.append(selection)
            if len(picked) >= markets_per_match:
                break
        return picked

    @staticmethod
    def _event_sort_key(selection: OddsSelection) -> tuple[str, str, str]:
        return (
            selection.event_start_time.isoformat() if selection.event_start_time else "",
            selection.league,
            selection.match_name,
        )

    @staticmethod
    def _is_supported_selection_context(selection: OddsSelection) -> bool:
        haystack = " | ".join(
            part for part in [selection.league, selection.match_name, selection.home_team, selection.away_team] if part
        ).lower()
        blocked_tokens = [
            "статистика",
            "угл",
            "жк",
            "офсайд",
            "офсайды",
            "фолы",
            "удары",
            "в створ",
            "вброс",
        ]
        return not any(token in haystack for token in blocked_tokens)

    @staticmethod
    def _classify_candidate(selection: OddsSelection) -> tuple[str, str]:
        market = selection.market
        odds = selection.odds
        if market in {"1", "X", "2"}:
            if 1.4 <= odds <= 4.5:
                return "core", "Базовый исход матча в рабочем диапазоне кэфов."
            return "watch", "Исход матча есть, но кэф на границе удобного диапазона."
        if market in {"Over 2.5", "Under 2.5"}:
            if 1.55 <= odds <= 2.8:
                return "core", "Тотал 2.5 хорошо подходит для первой версии модели."
            return "watch", "Тотал 2.5 есть, но цена выглядит более рискованной."
        if market in {"BTTS Yes", "BTTS No"}:
            if 1.55 <= odds <= 2.60:
                return "core", "Обе забьют хорошо подходят для первого BTTS-слоя модели."
            return "watch", "BTTS есть, но цена выглядит более пограничной."
        if market in {"1X", "X2", "12"}:
            return "secondary", "Двойной шанс можно держать как запасной рынок."
        return "watch", "Рынок пригоден для наблюдения, но пока не в приоритете."
