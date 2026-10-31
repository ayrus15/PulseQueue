"""Async SQLAlchemy engine and session factory construction."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def createEngine(
    databaseUrl: str,
    connectTimeoutSeconds: float = 10.0,
    commandTimeoutSeconds: float = 30.0,
    poolTimeoutSeconds: float = 10.0,
) -> AsyncEngine:
    """``connectTimeoutSeconds`` bounds establishing a new connection;
    ``commandTimeoutSeconds`` (asyncpg's own per-query timeout) bounds a
    single query on an already-open connection; ``poolTimeoutSeconds``
    bounds how long a caller waits for a free connection from the pool.
    Without these, any one of "PostgreSQL never answers", "a query hangs",
    or "the pool is exhausted" would block forever instead of failing
    fast (FR9 / Phase 8's "set connection, request, and task execution
    timeouts").
    """
    return create_async_engine(
        databaseUrl,
        pool_pre_ping=True,
        pool_timeout=poolTimeoutSeconds,
        connect_args={
            "timeout": connectTimeoutSeconds,
            "command_timeout": commandTimeoutSeconds,
        },
    )


def createSessionFactory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
