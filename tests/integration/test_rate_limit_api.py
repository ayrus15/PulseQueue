"""Integration tests proving the rate limit dependency actually enforces
a limit against real Redis when enabled, and is a no-op by default.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from pulsequeue.core.config import Settings, getSettings
from pulsequeue.main import createApp
from pulsequeue.persistence.database import createSessionFactory
from pulsequeue.queueing.redisQueue import createRedisClient

_SUBMISSION = {
    "taskType": "generateReport",
    "payload": {"reportName": "x", "periodDays": 1},
}


@pytest_asyncio.fixture
async def rateLimitedClient(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    application = createApp()
    application.state.sessionFactory = createSessionFactory(engine)
    enabledSettings = Settings(
        PULSEQUEUE_RATE_LIMIT_ENABLED=True, PULSEQUEUE_RATE_LIMIT_PER_MINUTE=2
    )
    application.dependency_overrides[getSettings] = lambda: enabledSettings
    redisClient = createRedisClient(enabledSettings.redisUrl)
    application.state.redisClient = redisClient
    transport = ASGITransport(app=application)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as httpClient:
            yield httpClient
    finally:
        await redisClient.aclose()


async def testRequestsWithinTheLimitSucceed(rateLimitedClient: AsyncClient) -> None:
    for _ in range(2):
        response = await rateLimitedClient.post("/api/v1/tasks", json=_SUBMISSION)
        assert response.status_code == 201


async def testExceedingTheLimitReturns429(rateLimitedClient: AsyncClient) -> None:
    for _ in range(2):
        await rateLimitedClient.post("/api/v1/tasks", json=_SUBMISSION)

    response = await rateLimitedClient.post("/api/v1/tasks", json=_SUBMISSION)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RateLimitExceededError"


@pytest_asyncio.fixture
async def defaultClient(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
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


async def testRateLimitingIsOffByDefault(defaultClient: AsyncClient) -> None:
    """Settings here come from the real environment -
    PULSEQUEUE_RATE_LIMIT_ENABLED is unset, so many requests in a row
    must all succeed rather than being throttled.
    """
    for _ in range(10):
        response = await defaultClient.post("/api/v1/tasks", json=_SUBMISSION)
        assert response.status_code == 201
