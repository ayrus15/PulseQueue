"""Integration tests for /health/live and /health/ready."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from pulsequeue.core.config import getSettings
from pulsequeue.main import createApp
from pulsequeue.persistence.database import createSessionFactory
from pulsequeue.queueing.redisQueue import createRedisClient


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    application = createApp()
    application.state.sessionFactory = createSessionFactory(engine)
    redisClient = createRedisClient(getSettings().redisUrl)
    application.state.redisClient = redisClient
    transport = ASGITransport(app=application)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as httpClient:
            yield httpClient
    finally:
        await redisClient.aclose()


async def testLiveAlwaysReturns200(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def testReadyReturns200WhenDatabaseIsReachable(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"


@pytest_asyncio.fixture
async def clientWithUnreachableRedis(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    application = createApp()
    application.state.sessionFactory = createSessionFactory(engine)
    redisClient = createRedisClient("redis://localhost:1/0")
    application.state.redisClient = redisClient
    transport = ASGITransport(app=application)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as httpClient:
            yield httpClient
    finally:
        await redisClient.aclose()


async def testReadyStaysReadyWhenOnlyRedisIsUnreachable(
    clientWithUnreachableRedis: AsyncClient,
) -> None:
    """Redis is best-effort (ADR 0002) - its outage must never fail
    readiness, only be reported.
    """
    response = await clientWithUnreachableRedis.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"
    assert body["redis"] == "unreachable"
