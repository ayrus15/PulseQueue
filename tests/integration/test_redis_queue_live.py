"""Verifies notifyTaskReady/waitForNotification against a real Redis
server - tests/unit/test_redis_queue.py already covers the "Redis is
unreachable" paths with fakes; this covers the actual happy path.

Skips cleanly (not fails) if no Redis is reachable, matching the
PostgreSQL integration tests' convention.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from pulsequeue.queueing.redisQueue import createRedisClient, notifyTaskReady, waitForNotification

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")


@pytest_asyncio.fixture
async def redisClient() -> AsyncIterator[object]:
    client = createRedisClient(REDIS_URL)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"No reachable Redis at {REDIS_URL!r} ({exc.__class__.__name__}: {exc})")
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


async def testWaitForNotificationReturnsTrueAfterARealNotify(redisClient: object) -> None:
    await notifyTaskReady(redisClient)  # type: ignore[arg-type]
    result = await waitForNotification(redisClient, timeoutSeconds=2)  # type: ignore[arg-type]
    assert result is True


async def testWaitForNotificationTimesOutWithNoNotification(redisClient: object) -> None:
    result = await waitForNotification(redisClient, timeoutSeconds=1)  # type: ignore[arg-type]
    assert result is False
