"""FastAPI dependency wiring: one DB session per request, plus the
process-wide Redis client stashed on app.state by main.py's lifespan.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession


async def getSession(request: Request) -> AsyncIterator[AsyncSession]:
    sessionFactory = request.app.state.sessionFactory
    async with sessionFactory() as session:
        yield session


def getRedisClient(request: Request) -> Redis:
    return cast(Redis, request.app.state.redisClient)
