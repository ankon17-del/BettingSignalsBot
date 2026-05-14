from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SignalStatus, User
from app.db.repositories import SignalRepository


@dataclass
class Stats:
    total: int
    closed: int
    pending: int
    won: int
    lost: int
    void: int
    winrate: float
    roi: float
    profit: float
    current_bankroll: float
    initial_bankroll: float
    avg_odds: float
    avg_value: float
    max_drawdown: float


class StatsService:
    def __init__(self, session: AsyncSession) -> None:
        self.signals = SignalRepository(session)

    async def get_stats(
        self,
        user: User,
        league: str | None = None,
        market: str | None = None,
        risk_level: str | None = None,
        confidence: str | None = None,
        month: str | None = None,
    ) -> Stats:
        signals = await self.signals.list_for_stats(league, market, risk_level, confidence, month)
        closed_signals = [s for s in signals if s.status in {SignalStatus.won, SignalStatus.lost, SignalStatus.void}]
        won = sum(1 for s in closed_signals if s.status == SignalStatus.won)
        lost = sum(1 for s in closed_signals if s.status == SignalStatus.lost)
        void = sum(1 for s in closed_signals if s.status == SignalStatus.void)
        settled = won + lost
        total_staked = sum(s.recommended_stake for s in closed_signals if s.status != SignalStatus.void)
        profit = round(sum(s.profit for s in closed_signals), 2)
        winrate = round(won / settled * 100, 2) if settled else 0.0
        roi = round(profit / total_staked * 100, 2) if total_staked else 0.0
        avg_odds = round(sum(s.odds for s in signals) / len(signals), 2) if signals else 0.0
        avg_value = round(sum(s.value_percent for s in signals) / len(signals), 2) if signals else 0.0
        max_drawdown = self._max_drawdown(user.initial_bankroll, closed_signals)
        return Stats(
            total=len(signals),
            closed=len(closed_signals),
            pending=sum(1 for s in signals if s.status == SignalStatus.pending),
            won=won,
            lost=lost,
            void=void,
            winrate=winrate,
            roi=roi,
            profit=profit,
            current_bankroll=user.bankroll,
            initial_bankroll=user.initial_bankroll,
            avg_odds=avg_odds,
            avg_value=avg_value,
            max_drawdown=max_drawdown,
        )

    @staticmethod
    def _max_drawdown(initial_bankroll: float, signals: list) -> float:
        peak = initial_bankroll
        bankroll = initial_bankroll
        max_dd = 0.0
        for signal in sorted(signals, key=lambda item: item.closed_at or item.created_at):
            bankroll += signal.profit
            peak = max(peak, bankroll)
            if peak:
                drawdown = (bankroll - peak) / peak * 100
                max_dd = min(max_dd, drawdown)
        return round(max_dd, 2)

