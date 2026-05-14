from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NewsItem, Signal, SignalStatus, User
from app.db.repositories import BankrollHistoryRepository, SignalRepository, utcnow
from app.engine.bankroll import calculate_profit, calculate_recommended_stake, get_stake_percent
from app.engine.value_detector import bookmaker_probability, value_percent


class SignalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.signals = SignalRepository(session)
        self.history = BankrollHistoryRepository(session)

    async def create_test_signal(self, user: User) -> Signal:
        odds = 2.10
        model_probability = 0.56
        book_probability = bookmaker_probability(odds)
        value = value_percent(model_probability, odds)
        stake_percent = get_stake_percent(user.risk_profile.value, value, "medium", user.base_unit_percent)
        recommended_stake = calculate_recommended_stake(user.bankroll, stake_percent)
        signal = Signal(
            sport="football",
            league="Premier League",
            match_name="Team A - Team B",
            home_team="Team A",
            away_team="Team B",
            market="Over 2.5",
            bookmaker_name="Demo Bookmaker",
            odds=odds,
            bookmaker_probability=book_probability,
            model_probability=model_probability,
            value_percent=value,
            confidence="medium",
            risk_level="medium",
            stake_percent=stake_percent,
            recommended_stake=recommended_stake,
            status=SignalStatus.pending,
            match_start_time=utcnow() + timedelta(days=1),
        )
        news = NewsItem(
            title="Основной нападающий гостей под вопросом",
            source_url=None,
            source_type="demo",
            reliability="medium",
            impact="medium",
            affected_team="Team B",
            affected_player=None,
        )
        return await self.signals.create(signal, [news])

    async def list_active_signals(self) -> list[Signal]:
        return await self.signals.list_pending()

    async def close_signal(self, user: User, signal_id: int, status: str) -> Signal | None:
        signal = await self.signals.get(signal_id)
        if signal is None or signal.status != SignalStatus.pending:
            return signal

        before = user.bankroll
        profit = calculate_profit(status, signal.recommended_stake, signal.odds)
        after = round(before + profit, 2)

        signal.status = SignalStatus(status)
        signal.profit = profit
        signal.closed_at = utcnow()
        user.bankroll = after

        await self.history.add(user.id, signal.id, before, after, f"signal_{status}")
        return signal

