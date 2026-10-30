"""FastAPI dependency wiring: one DB session per request, plus the
process-wide Redis client stashed on app.state by main.py's lifespan.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from typing import cast

from fastapi import Depends, Header, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.api.rateLimit import checkRateLimit
from pulsequeue.core.config import Settings, getSettings
from pulsequeue.domain.errors import RateLimitExceededError, UnauthorizedError


async def getSession(request: Request) -> AsyncIterator[AsyncSession]:
    sessionFactory = request.app.state.sessionFactory
    async with sessionFactory() as session:
        yield session


def getRedisClient(request: Request) -> Redis:
    return cast(Redis, request.app.state.redisClient)


def requireAdminToken(
    adminToken: str | None = Header(default=None, alias="X-Admin-Token"),
    settings: Settings = Depends(getSettings),
) -> None:
    """Protects administrative endpoints (dead-letter inspection/requeue)
    with a shared secret, until real per-client authentication exists -
    see docs/threatModel.md. ``secrets.compare_digest`` avoids leaking
    the token's value through response-time differences.
    """
    if adminToken is None or not secrets.compare_digest(adminToken, settings.adminToken):
        raise UnauthorizedError("Missing or invalid X-Admin-Token header")


async def enforceSubmissionRateLimit(
    request: Request,
    redisClient: Redis = Depends(getRedisClient),
    settings: Settings = Depends(getSettings),
) -> None:
    """A no-op unless PULSEQUEUE_RATE_LIMIT_ENABLED is set - see
    api/rateLimit.py for why it's off by default and fails open.
    """
    if not settings.rateLimitEnabled:
        return
    clientHost = request.client.host if request.client else "unknown"
    allowed = await checkRateLimit(
        redisClient,
        key=f"submitTask:{clientHost}",
        limit=settings.rateLimitPerMinute,
        windowSeconds=60,
    )
    if not allowed:
        raise RateLimitExceededError(
            f"Rate limit of {settings.rateLimitPerMinute} requests/minute exceeded"
        )
