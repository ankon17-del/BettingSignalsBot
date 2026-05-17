from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HealthStatus


class HealthStatusRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, component_type: str, component_name: str) -> HealthStatus | None:
        result = await self.session.execute(
            select(HealthStatus).where(
                HealthStatus.component_type == component_type,
                HealthStatus.component_name == component_name,
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[HealthStatus]:
        result = await self.session.execute(
            select(HealthStatus).order_by(HealthStatus.component_type.asc(), HealthStatus.component_name.asc())
        )
        return list(result.scalars().all())

    async def upsert(self, component_type: str, component_name: str, payload: dict) -> HealthStatus:
        item = await self.get(component_type, component_name)
        if item is None:
            item = HealthStatus(component_type=component_type, component_name=component_name)
            self.session.add(item)

        for key, value in payload.items():
            setattr(item, key, value)

        await self.session.flush()
        return item
