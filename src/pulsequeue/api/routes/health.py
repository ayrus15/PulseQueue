"""GET /health/live and GET /health/ready."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.api.dependencies import getRedisClient, getSession
from pulsequeue.observability.health import checkDatabase, checkRedis

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    """Process liveness only - no dependency checks. If this doesn't
    respond, the process itself is the problem."""
    return {"status": "alive"}


@router.get("/ready")
async def ready(
    response: Response,
    session: AsyncSession = Depends(getSession),
    redisClient: Redis = Depends(getRedisClient),
) -> dict[str, str]:
    """Database is the actual correctness dependency (ADR 0001), so its
    outage fails readiness (503). Redis is best-effort (ADR 0002) - its
    outage is reported here but never fails readiness, consistent with
    the rest of the system treating it as optional.
    """
    databaseOk = await checkDatabase(session)
    redisOk = await checkRedis(redisClient)

    if not databaseOk:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if databaseOk else "not_ready",
        "database": "ok" if databaseOk else "unreachable",
        "redis": "ok" if redisOk else "unreachable",
    }
