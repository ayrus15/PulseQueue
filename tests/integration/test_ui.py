"""Integration test for the /ui static dashboard mount (Phase 9)."""

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


async def testUiIndexIsServed(client: AsyncClient) -> None:
    response = await client.get("/ui/")
    assert response.status_code == 200
    assert "PulseQueue" in response.text


async def testUiStaticAssetsAreServed(client: AsyncClient) -> None:
    for path in ("/ui/styles.css", "/ui/app.js"):
        response = await client.get(path)
        assert response.status_code == 200, path


async def testUiDoesNotShadowApiRoutes(client: AsyncClient) -> None:
    """The /ui mount must never intercept requests meant for the real
    API - it's registered under its own prefix precisely so there's no
    routing ambiguity to get wrong here.
    """
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
