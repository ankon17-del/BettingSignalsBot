from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User
from app.db.repositories import BankrollHistoryRepository, UserRepository


class BankrollService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.history = BankrollHistoryRepository(session)

    async def get_or_create_user(self, telegram_id: int, username: str | None) -> User:
        user = await self.users.get_by_telegram_id(telegram_id)
        if user:
            if username and user.username != username:
                user.username = username
            return user
        return await self.users.create(
            telegram_id=telegram_id,
            username=username,
            bankroll=self.settings.default_bankroll,
            unit_percent=self.settings.default_unit_percent,
            risk_profile=self.settings.default_risk_profile,
        )

    async def set_bankroll(self, user: User, amount: float) -> User:
        before = user.bankroll
        user.bankroll = amount
        if before == self.settings.default_bankroll and user.initial_bankroll == self.settings.default_bankroll:
            user.initial_bankroll = amount
        await self.history.add(user.id, None, before, amount, "manual_bankroll_update")
        return user

    async def set_unit_percent(self, user: User, unit_percent: float) -> User:
        user.base_unit_percent = unit_percent
        return user

    async def set_risk_profile(self, user: User, risk_profile: str) -> User:
        user.risk_profile = risk_profile
        return user
