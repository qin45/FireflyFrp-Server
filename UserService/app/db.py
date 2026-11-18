from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


engine: AsyncEngine | None = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str) -> None:
    global engine, SessionLocal
    engine = create_async_engine(url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def init_db() -> None:
    if engine is None:
        raise RuntimeError("database engine is not initialized")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_engine() -> None:
    global engine, SessionLocal
    if engine is not None:
        await engine.dispose()
    engine = None
    SessionLocal = None


async def get_db() -> AsyncIterator[AsyncSession]:
    if SessionLocal is None:
        raise RuntimeError("database is not initialized")
    async with SessionLocal() as session:
        yield session


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def with_for_update(stmt: Select, session: AsyncSession) -> Select:
    """Use SELECT ... FOR UPDATE on MySQL; SQLite has no such syntax."""
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "mysql":
        return stmt.with_for_update()
    return stmt
