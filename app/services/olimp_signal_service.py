from collections import defaultdict

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


class OlimpSignalGenerationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.signals = SignalRepository(session)
        self.odds_feed = OddsFeedService(settings)

    async def generate_signals(self, user: User, match_limit: int = 5) -> list[Signal]:
        selections = await self.odds_feed.fetch_olimp_filtered_selections(match_limit=match_limit, markets_per_match=5)
        pending_signals = await self.signals.list_pending(limit=200)
        existing_keys = {
            (signal.league.lower(), signal.match_name.lower(), signal.market.lower(), signal.bookmaker_name.lower())
            for signal in pending_signals
        }

        grouped: dict[str, list[OddsSelection]] = defaultdict(list)
        for selection in selections:
            event_key = selection.source_event_id or f"{selection.match_name}|{selection.league}"
            grouped[event_key].append(selection)

        created: list[Signal] = []
        for event_selections in grouped.values():
            model_probabilities = estimate_match_probabilities(event=event_selections[0])
            for selection in event_selections:
                market_key = self._market_probability_key(selection.market)
                if market_key is None:
                    continue
                key = (
                    selection.league.lower(),
                    selection.match_name.lower(),
                    selection.market.lower(),
                    selection.bookmaker_name.lower(),
                )
                if key in existing_keys:
                    continue

                model_probability = model_probabilities.get(market_key)
                if model_probability is None:
                    continue
                book_probability = bookmaker_probability(selection.odds)
                edge = value_percent(model_probability, selection.odds)
                confidence = self._confidence_from_edge(edge)
                risk_level = adjust_risk_level(confidence, has_negative_news=False)
                if not is_value_signal(model_probability, selection.odds, risk_level):
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
                created_signal = await self.signals.create(signal)
                created.append(created_signal)
                existing_keys.add(key)
        return created

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
