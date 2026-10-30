"""GET /metrics - Prometheus exposition format."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.api.dependencies import getRedisClient, getSession
from pulsequeue.observability.metrics import renderMetrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics(
    session: AsyncSession = Depends(getSession),
    redisClient: Redis = Depends(getRedisClient),
) -> Response:
    body = await renderMetrics(session, redisClient)
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)
