"""Unit tests for the Redis queue adapter's best-effort error handling
(ADR 0002) - no real Redis needed, since the whole point is what
happens when Redis isn't reachable.
"""

from __future__ import annotations

from typing import Any

import pytest

from pulsequeue.queueing.redisQueue import notifyTaskReady, waitForNotification


class _FailingRedis:
    async def rpush(self, *args: Any, **kwargs: Any) -> int:
        raise ConnectionError("simulated: Redis unreachable")

    async def blpop(self, *args: Any, **kwargs: Any) -> list[Any]:
        raise ConnectionError("simulated: Redis unreachable")


class _WorkingRedis:
    def __init__(self) -> None:
        self.pushed: list[Any] = []

    async def rpush(self, key: str, value: str) -> int:
        self.pushed.append((key, value))
        return 1

    async def blpop(self, keys: list[str], timeout: int) -> tuple[str, str] | None:
        return (keys[0], "1") if self.pushed else None


@pytest.mark.parametrize("redisClient", [_FailingRedis()])
async def testNotifyTaskReadyNeverRaisesWhenRedisIsUnreachable(redisClient: _FailingRedis) -> None:
    await notifyTaskReady(redisClient)  # type: ignore[arg-type]


@pytest.mark.parametrize("redisClient", [_FailingRedis()])
async def testWaitForNotificationReturnsFalseWhenRedisIsUnreachable(
    redisClient: _FailingRedis,
) -> None:
    result = await waitForNotification(redisClient, timeoutSeconds=1)  # type: ignore[arg-type]
    assert result is False


async def testNotifyThenWaitReturnsTrueWhenATokenIsAvailable() -> None:
    redisClient = _WorkingRedis()
    await notifyTaskReady(redisClient)  # type: ignore[arg-type]
    result = await waitForNotification(redisClient, timeoutSeconds=1)  # type: ignore[arg-type]
    assert result is True


async def testWaitForNotificationReturnsFalseWithNoTokenAvailable() -> None:
    redisClient = _WorkingRedis()
    result = await waitForNotification(redisClient, timeoutSeconds=1)  # type: ignore[arg-type]
    assert result is False
