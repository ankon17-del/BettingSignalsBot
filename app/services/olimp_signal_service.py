from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.odds_collector import OddsSelection
from app.config import Settings
from app.db.models import Signal, SignalStatus, User
from app.db.repositories import SignalRepository
from app.engine.bankroll import calculate_recommended_stake, get_stake_percent
from app.engine.poisson import estimate_match_probabilities
from app.engine.risk_adjuster import adjust_risk_level
from app.engine.value_detector import bookmaker_probability, is_value_signal, value_percent
from app.services.odds_service import OddsFeedService


@dataclass(slots=True)
class GeneratedDraftSignal:
    selection: OddsSelection
    signal: Signal
    edge: float


@dataclass(slots=True)
class OlimpGenerationRunResult:
    created_signals: list[Signal] = field(default_factory=list)
    existing_pending_matches: int = 0
    passed_filters_matches: int = 0


@dataclass(slots=True)
class OlimpGenerationDebugEntry:
    selection: OddsSelection
    status: str
    reason: str
    bookmaker_probability: float | None = None
    model_probability: float | None = None
    edge: float | None = None


class OlimpSignalGenerationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.signals = SignalRepository(session)
        self.odds_feed = OddsFeedService(settings)

    async def generate_signals(
        self,
        user: User,
        match_limit: int = 8,
        create_limit: int | None = None,
        league_filter: str | None = None,
    ) -> OlimpGenerationRunResult:
        create_limit = create_limit or self.settings.olimp_max_signals_per_run
        scan_match_limit = max(match_limit, create_limit * 10, 30)
        selections = await self.odds_feed.fetch_olimp_filtered_selections(
            match_limit=scan_match_limit,
            markets_per_match=5,
        )
        pending_signals = await self.signals.list_pending(limit=300)
        existing_keys = {
            (signal.league.lower(), signal.match_name.lower(), signal.market.lower(), signal.bookmaker_name.lower())
            for signal in pending_signals
        }

        result = OlimpGenerationRunResult()
        draft_pool: list[GeneratedDraftSignal] = []
        seen_passing_events: set[str] = set()
        seen_existing_events: set[str] = set()

        for selection in selections:
            if not self._passes_generation_filters(selection, league_filter):
                continue

            market_key = self._market_probability_key(selection.market)
            if market_key is None:
                continue

            model_probabilities = estimate_match_probabilities(event=selection)
            model_probability = model_probabilities.get(market_key)
            if model_probability is None:
                continue

            book_probability = bookmaker_probability(selection.odds)
            edge = value_percent(model_probability, selection.odds)
            confidence = self._confidence_from_edge(edge)
            risk_level = adjust_risk_level(confidence, has_negative_news=False)
            if not is_value_signal(model_probability, selection.odds, risk_level):
                continue

            event_key = selection.source_event_id or selection.match_name.lower()
            if event_key not in seen_passing_events:
                result.passed_filters_matches += 1
                seen_passing_events.add(event_key)

            key = (
                selection.league.lower(),
                selection.match_name.lower(),
                selection.market.lower(),
                selection.bookmaker_name.lower(),
            )
            if key in existing_keys:
                if event_key not in seen_existing_events:
                    result.existing_pending_matches += 1
                    seen_existing_events.add(event_key)
                continue

            risk_profile = getattr(user.risk_profile, "value", user.risk_profile)
            stake_percent = get_stake_percent(str(risk_profile), edge, risk_level, user.base_unit_percent)
            recommended_stake = calculate_recommended_stake(user.bankroll, stake_percent)
            signal = Signal(
                sport=selection.sport.lower(),
                league=selection.league,
                match_name=selection.match_name,
                home_team=selection.home_team,
                away_team=selection.away_team,
                market=selection.market,
                bookmaker_name="OLIMP",
                odds=selection.odds,
                bookmaker_probability=book_probability,
                model_probability=model_probability,
                value_percent=edge,
                confidence=confidence,
                risk_level=risk_level,
                stake_percent=stake_percent,
                recommended_stake=recommended_stake,
                status=SignalStatus.pending,
                match_start_time=selection.event_start_time,
            )
            draft_pool.append(GeneratedDraftSignal(selection=selection, signal=signal, edge=edge))

        draft_pool.sort(
            key=lambda item: (
                self._league_priority_rank(item.selection.league),
                -item.edge,
                item.selection.event_start_time.isoformat() if item.selection.event_start_time else "",
                item.selection.league,
                item.selection.match_name,
            )
        )

        created_events: set[str] = set()
        for draft in draft_pool:
            if len(result.created_signals) >= create_limit:
                break
            event_key = draft.selection.source_event_id or draft.selection.match_name.lower()
            if event_key in created_events:
                continue
            created_signal = await self.signals.create(draft.signal)
            result.created_signals.append(created_signal)
            created_events.add(event_key)
            existing_keys.add(
                (
                    draft.selection.league.lower(),
                    draft.selection.match_name.lower(),
                    draft.selection.market.lower(),
                    draft.selection.bookmaker_name.lower(),
                )
            )
        return result

    async def inspect_generation(
        self,
        match_limit: int = 5,
        league_filter: str | None = None,
    ) -> list[OlimpGenerationDebugEntry]:
        scan_match_limit = max(match_limit * 3, 12)
        selections = await self.odds_feed.fetch_olimp_filtered_selections(
            match_limit=scan_match_limit,
            markets_per_match=5,
            league_filter=league_filter,
        )
        pending_signals = await self.signals.list_pending(limit=300)
        existing_keys = {
            (signal.league.lower(), signal.match_name.lower(), signal.market.lower(), signal.bookmaker_name.lower())
            for signal in pending_signals
        }

        result: list[OlimpGenerationDebugEntry] = []
        seen_events: set[str] = set()

        for selection in selections:
            event_key = selection.source_event_id or selection.match_name.lower()
            if len(seen_events) >= match_limit and event_key not in seen_events:
                continue

            status, reason, model_probability, edge = self._inspect_selection(selection, league_filter, existing_keys)
            result.append(
                OlimpGenerationDebugEntry(
                    selection=selection,
                    status=status,
                    reason=reason,
                    bookmaker_probability=bookmaker_probability(selection.odds),
                    model_probability=model_probability,
                    edge=edge,
                )
            )
            seen_events.add(event_key)

        return result

    def _inspect_selection(
        self,
        selection: OddsSelection,
        league_filter: str | None,
        existing_keys: set[tuple[str, str, str, str]],
    ) -> tuple[str, str, float | None, float | None]:
        league = selection.league.strip()
        league_lower = league.lower()

        if league_filter and league_filter.lower() not in league_lower:
            return "filtered", "Не совпал фильтр league=.", None, None

        if not (self.settings.olimp_signal_min_odds <= selection.odds <= self.settings.olimp_signal_max_odds):
            return (
                "filtered",
                f"Кэф вне рабочего диапазона {self.settings.olimp_signal_min_odds:.2f}-{self.settings.olimp_signal_max_odds:.2f}.",
                None,
                None,
            )

        blocklist = [item.lower() for item in self.settings.olimp_signal_league_blocklist]
        if any(token in league_lower for token in blocklist):
            return "filtered", "Лига попала в blocklist.", None, None

        allowlist = [item.lower() for item in self.settings.olimp_signal_league_allowlist]
        if allowlist and not any(token in league_lower for token in allowlist):
            return "filtered", "Лига не входит в allowlist.", None, None

        market_key = self._market_probability_key(selection.market)
        if market_key is None:
            return "filtered", "Рынок пока не поддерживается генератором.", None, None

        model_probabilities = estimate_match_probabilities(event=selection)
        model_probability = model_probabilities.get(market_key)
        if model_probability is None:
            return "filtered", "Для рынка нет model probability.", None, None

        edge = value_percent(model_probability, selection.odds)
        confidence = self._confidence_from_edge(edge)
        risk_level = adjust_risk_level(confidence, has_negative_news=False)
        if not is_value_signal(model_probability, selection.odds, risk_level):
            return "filtered", "Не прошёл value-фильтр текущего stub.", model_probability, edge

        key = (
            selection.league.lower(),
            selection.match_name.lower(),
            selection.market.lower(),
            selection.bookmaker_name.lower(),
        )
        if key in existing_keys:
            return "pending", self._pending_reason(selection.league), model_probability, edge

        return "ready", self._ready_reason(selection.league), model_probability, edge

    def _passes_generation_filters(self, selection: OddsSelection, league_filter: str | None) -> bool:
        league = selection.league.strip()
        league_lower = league.lower()
        if league_filter and league_filter.lower() not in league_lower:
            return False

        if not (self.settings.olimp_signal_min_odds <= selection.odds <= self.settings.olimp_signal_max_odds):
            return False

        blocklist = [item.lower() for item in self.settings.olimp_signal_league_blocklist]
        if any(token in league_lower for token in blocklist):
            return False

        allowlist = [item.lower() for item in self.settings.olimp_signal_league_allowlist]
        if allowlist and not any(token in league_lower for token in allowlist):
            return False

        return True

    @staticmethod
    def _market_probability_key(market: str) -> str | None:
        if market == "Over 2.5":
            return "over_2_5"
        if market == "Under 2.5":
            return "under_2_5"
        return None

    @staticmethod
    def _confidence_from_edge(edge: float) -> str:
        if edge >= 8:
            return "high"
        if edge >= 5:
            return "medium"
        return "low"

    def _league_priority_rank(self, league: str) -> int:
        priorities = [item.lower() for item in self.settings.olimp_signal_priority_leagues]
        league_lower = league.lower()
        for index, token in enumerate(priorities):
            if token and token in league_lower:
                return index
        return len(priorities) + 100

    def _is_priority_league(self, league: str) -> bool:
        priorities = [item.lower() for item in self.settings.olimp_signal_priority_leagues]
        league_lower = league.lower()
        return any(token and token in league_lower for token in priorities)

    def _ready_reason(self, league: str) -> str:
        if self._is_priority_league(league):
            return "Готов к созданию draft signal. Лига в приоритетном списке."
        return "Готов к созданию draft signal."

    def _pending_reason(self, league: str) -> str:
        if self._is_priority_league(league):
            return "По этому рынку уже есть pending signal. Лига в приоритетном списке."
        return "По этому рынку уже есть pending signal."
