"""Dependency health checks, used by GET /health/ready."""

from __future__ import annotations

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def checkDatabase(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def checkRedis(redisClient: Redis) -> bool:
    try:
        await redisClient.ping()
        return True
    except Exception:
        return False
