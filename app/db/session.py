from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


engine: AsyncEngine | None = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


def create_db_engine(database_url: str) -> AsyncEngine:
    global engine, SessionLocal
    engine = create_async_engine(database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    return engine


async def dispose_db_engine() -> None:
    if engine is not None:
        await engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    if SessionLocal is None:
        raise RuntimeError("Database engine is not initialized")
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def session_context() -> AsyncIterator[AsyncSession]:
    if SessionLocal is None:
        raise RuntimeError("Database engine is not initialized")
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
