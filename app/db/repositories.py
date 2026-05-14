from datetime import datetime, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import BankrollHistory, NewsItem, Signal, SignalNewsLink, SignalStatus, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def create(self, telegram_id: int, username: str | None, bankroll: float, unit_percent: float, risk_profile: str) -> User:
        user = User(
            telegram_id=telegram_id,
            username=username,
            bankroll=bankroll,
            initial_bankroll=bankroll,
            base_unit_percent=unit_percent,
            risk_profile=risk_profile,
        )
        self.session.add(user)
        await self.session.flush()
        return user


class SignalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, signal: Signal, news_items: list[NewsItem] | None = None) -> Signal:
        self.session.add(signal)
        if news_items:
            for news_item in news_items:
                link = SignalNewsLink(signal=signal, news_item=news_item)
                self.session.add_all([news_item, link])
        await self.session.flush()
        return signal

    async def get(self, signal_id: int) -> Signal | None:
        result = await self.session.execute(
            select(Signal).options(selectinload(Signal.news_links).selectinload(SignalNewsLink.news_item)).where(Signal.id == signal_id)
        )
        return result.scalar_one_or_none()

    async def list_pending(self, limit: int = 10) -> list[Signal]:
        result = await self.session.execute(
            select(Signal)
            .where(Signal.status == SignalStatus.pending)
            .order_by(Signal.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_for_stats(
        self,
        league: str | None = None,
        market: str | None = None,
        risk_level: str | None = None,
        confidence: str | None = None,
        month: str | None = None,
    ) -> list[Signal]:
        stmt: Select[tuple[Signal]] = select(Signal)
        if league:
            stmt = stmt.where(func.lower(Signal.league) == league.lower())
        if market:
            stmt = stmt.where(func.lower(Signal.market) == market.lower())
        if risk_level:
            stmt = stmt.where(func.lower(Signal.risk_level) == risk_level.lower())
        if confidence:
            stmt = stmt.where(func.lower(Signal.confidence) == confidence.lower())
        if month:
            stmt = stmt.where(func.to_char(Signal.created_at, "YYYY-MM") == month)
        result = await self.session.execute(stmt.order_by(Signal.created_at.asc()))
        return list(result.scalars().all())


class BankrollHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, user_id: int, signal_id: int | None, before: float, after: float, reason: str) -> BankrollHistory:
        item = BankrollHistory(
            user_id=user_id,
            signal_id=signal_id,
            bankroll_before=before,
            bankroll_after=after,
            change_amount=after - before,
            reason=reason,
        )
        self.session.add(item)
        await self.session.flush()
        return item


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
