from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.api_football_collector import ApiFootballCollector, ApiFootballFixtureContext
from app.config import Settings
from app.db.models import Signal, SignalStatus, User
from app.db.repositories import BankrollHistoryRepository, utcnow
from app.engine.bankroll import calculate_profit


COMPLETED_STATUSES = {"FT", "AET", "PEN"}
VOID_STATUSES = {"PST", "CANC", "ABD"}
SUPPORTED_MARKETS = {"1", "X", "2", "Over 2.5", "Under 2.5", "BTTS Yes", "BTTS No"}


@dataclass(slots=True)
class AutoSettlementEntry:
    signal: Signal
    final_status: SignalStatus
    scoreline: str | None
    provider_status: str | None
    history_reason: str


@dataclass(slots=True)
class AutoSettlementResult:
    checked_signals: int = 0
    resolved_signals: int = 0
    won_signals: int = 0
    lost_signals: int = 0
    void_signals: int = 0
    unresolved_signals: int = 0
    entries: list[AutoSettlementEntry] | None = None

    def __post_init__(self) -> None:
        if self.entries is None:
            self.entries = []


class AutoSettlementService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.api_football = ApiFootballCollector(settings)
        self.history = BankrollHistoryRepository(session)

    async def settle_pending_signals(self, user: User, limit: int = 25) -> AutoSettlementResult:
        pending_signals = await self._list_pending_football_signals(limit)
        result = AutoSettlementResult(checked_signals=len(pending_signals))
        if not pending_signals or not self.api_football.is_configured:
            result.unresolved_signals = len(pending_signals)
            return result

        fixtures_lookup = await self.api_football.build_signal_fixture_lookup(pending_signals)
        for signal in pending_signals:
            fixture = fixtures_lookup.get(signal.id)
            if fixture is None:
                result.unresolved_signals += 1
                continue

            settlement = self._resolve_market(signal.market, fixture)
            if settlement is None:
                result.unresolved_signals += 1
                continue

            final_status, scoreline = settlement
            reason = self._history_reason(final_status, scoreline, fixture.status_short)
            await self._apply_settlement(user, signal, final_status, reason)

            result.resolved_signals += 1
            if final_status == SignalStatus.won:
                result.won_signals += 1
            elif final_status == SignalStatus.lost:
                result.lost_signals += 1
            elif final_status == SignalStatus.void:
                result.void_signals += 1

            result.entries.append(
                AutoSettlementEntry(
                    signal=signal,
                    final_status=final_status,
                    scoreline=scoreline,
                    provider_status=fixture.status_short,
                    history_reason=reason,
                )
            )

        return result

    async def _list_pending_football_signals(self, limit: int) -> list[Signal]:
        cutoff = datetime.now(UTC) - timedelta(minutes=5)
        result = await self.session.execute(
            select(Signal)
            .where(
                Signal.status == SignalStatus.pending,
                Signal.sport == "football",
                Signal.market.in_(SUPPORTED_MARKETS),
                Signal.match_start_time.is_not(None),
                Signal.match_start_time <= cutoff,
            )
            .order_by(Signal.match_start_time.asc(), Signal.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    def _resolve_market(
        self,
        market: str,
        fixture: ApiFootballFixtureContext,
    ) -> tuple[SignalStatus, str | None] | None:
        provider_status = (fixture.status_short or "").upper()
        if provider_status in VOID_STATUSES:
            return SignalStatus.void, None
        if provider_status not in COMPLETED_STATUSES:
            return None

        home_goals = fixture.fulltime_home_goals
        away_goals = fixture.fulltime_away_goals
        if home_goals is None or away_goals is None:
            return None

        total_goals = home_goals + away_goals
        scoreline = f"{home_goals}:{away_goals}"

        if market == "1":
            return (SignalStatus.won if home_goals > away_goals else SignalStatus.lost), scoreline
        if market == "X":
            return (SignalStatus.won if home_goals == away_goals else SignalStatus.lost), scoreline
        if market == "2":
            return (SignalStatus.won if away_goals > home_goals else SignalStatus.lost), scoreline
        if market == "Over 2.5":
            return (SignalStatus.won if total_goals > 2 else SignalStatus.lost), scoreline
        if market == "Under 2.5":
            return (SignalStatus.won if total_goals < 3 else SignalStatus.lost), scoreline
        if market == "BTTS Yes":
            return (SignalStatus.won if home_goals > 0 and away_goals > 0 else SignalStatus.lost), scoreline
        if market == "BTTS No":
            return (SignalStatus.won if home_goals == 0 or away_goals == 0 else SignalStatus.lost), scoreline
        return None

    async def _apply_settlement(
        self,
        user: User,
        signal: Signal,
        final_status: SignalStatus,
        reason: str,
    ) -> None:
        latest_bankroll_state = await self.history.get_latest_for_user(user.id)
        before = latest_bankroll_state.bankroll_after if latest_bankroll_state is not None else user.bankroll
        profit = calculate_profit(final_status.value, signal.recommended_stake, signal.odds)
        after = round(before + profit, 2)

        signal.status = final_status
        signal.profit = profit
        signal.closed_at = utcnow()
        user.bankroll = after

        await self.history.add(user.id, signal.id, before, after, reason)

    @staticmethod
    def _history_reason(final_status: SignalStatus, scoreline: str | None, provider_status: str | None) -> str:
        base = f"auto_signal_{final_status.value}"
        meta = []
        if scoreline:
            meta.append(scoreline)
        if provider_status:
            meta.append(provider_status)
        return "|".join([base, *meta]) if meta else base
