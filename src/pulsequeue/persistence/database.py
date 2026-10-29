"""Async SQLAlchemy engine and session factory construction."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def createEngine(databaseUrl: str) -> AsyncEngine:
    return create_async_engine(databaseUrl, pool_pre_ping=True)


def createSessionFactory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
