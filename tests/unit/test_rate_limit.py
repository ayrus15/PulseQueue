"""Unit tests for the rate limiter's counting and fail-open behavior -
no real Redis needed.
"""

from __future__ import annotations

from typing import Any

import pytest

from pulsequeue.api.rateLimit import checkRateLimit


class _FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True


class _FailingRedis:
    async def incr(self, *args: Any, **kwargs: Any) -> int:
        raise ConnectionError("simulated: Redis unreachable")

    async def expire(self, *args: Any, **kwargs: Any) -> bool:
        raise ConnectionError("simulated: Redis unreachable")


async def testAllowsRequestsWithinTheLimit() -> None:
    redisClient = _FakeRedis()
    for _ in range(5):
        allowed = await checkRateLimit(redisClient, key="client-a", limit=5, windowSeconds=60)  # type: ignore[arg-type]
        assert allowed is True


async def testRejectsRequestsOverTheLimit() -> None:
    redisClient = _FakeRedis()
    for _ in range(3):
        await checkRateLimit(redisClient, key="client-b", limit=3, windowSeconds=60)  # type: ignore[arg-type]

    allowed = await checkRateLimit(redisClient, key="client-b", limit=3, windowSeconds=60)  # type: ignore[arg-type]
    assert allowed is False


async def testDifferentKeysHaveIndependentLimits() -> None:
    redisClient = _FakeRedis()
    for _ in range(3):
        await checkRateLimit(redisClient, key="client-c", limit=3, windowSeconds=60)  # type: ignore[arg-type]

    allowed = await checkRateLimit(redisClient, key="client-d", limit=3, windowSeconds=60)  # type: ignore[arg-type]
    assert allowed is True


@pytest.mark.parametrize("redisClient", [_FailingRedis()])
async def testFailsOpenWhenRedisIsUnreachable(redisClient: _FailingRedis) -> None:
    allowed = await checkRateLimit(redisClient, key="client-e", limit=1, windowSeconds=60)  # type: ignore[arg-type]
    assert allowed is True
