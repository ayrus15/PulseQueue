"""Unit tests for the health check functions' failure paths - no real
database or Redis needed.
"""

from __future__ import annotations

from typing import Any

from pulsequeue.observability.health import checkDatabase, checkRedis


class _FailingSession:
    async def execute(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError("simulated: database unreachable")


class _WorkingSession:
    async def execute(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FailingRedis:
    async def ping(self) -> bool:
        raise ConnectionError("simulated: Redis unreachable")


class _WorkingRedis:
    async def ping(self) -> bool:
        return True


async def testCheckDatabaseReturnsFalseWhenUnreachable() -> None:
    assert await checkDatabase(_FailingSession()) is False  # type: ignore[arg-type]


async def testCheckDatabaseReturnsTrueWhenReachable() -> None:
    assert await checkDatabase(_WorkingSession()) is True  # type: ignore[arg-type]


async def testCheckRedisReturnsFalseWhenUnreachable() -> None:
    assert await checkRedis(_FailingRedis()) is False  # type: ignore[arg-type]


async def testCheckRedisReturnsTrueWhenReachable() -> None:
    assert await checkRedis(_WorkingRedis()) is True  # type: ignore[arg-type]
