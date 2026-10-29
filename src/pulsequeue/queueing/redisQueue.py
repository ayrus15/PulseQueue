"""Redis-backed wake-up notifications.

Per ADR 0002, Redis is a latency optimization only, never a delivery
mechanism: every function here is best-effort and swallows its own
errors (logged, not raised). A worker's own database poll loop is the
actual correctness guarantee - this module only shortens how long an
idle worker waits before it notices new work.
"""

from __future__ import annotations

import logging
from typing import cast

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

WAKE_KEY = "pulsequeue:wake"


def createRedisClient(redisUrl: str) -> Redis:
    # redis-py's own type stubs type Redis.from_url as returning Any.
    return cast(Redis, Redis.from_url(redisUrl))


async def notifyTaskReady(redisClient: Redis) -> None:
    """Push a wake-up token so an idle worker's BLPOP returns immediately
    instead of waiting out its poll interval. Never raises.
    """
    try:
        # redis-py's command mixins are shared between the sync and async
        # clients, so mypy sees `Awaitable[int] | int` here even though this
        # client is always the async one.
        await redisClient.rpush(WAKE_KEY, "1")  # type: ignore[misc]
    except Exception:
        logger.warning("Failed to publish task-ready notification to Redis", exc_info=True)


async def waitForNotification(redisClient: Redis, timeoutSeconds: float) -> bool:
    """Block for up to ``timeoutSeconds`` for a wake-up token.

    Returns True if one arrived, False on timeout or any Redis error -
    the caller polls the database regardless either way, so a False here
    never means "no work", only "no low-latency hint this time."
    """
    # BLPOP's timeout is whole seconds; round up so callers never block
    # longer than they asked (and never pass 0, which means "forever").
    wholeSecondsTimeout = max(1, int(timeoutSeconds + 0.999))
    try:
        result = await redisClient.blpop([WAKE_KEY], timeout=wholeSecondsTimeout)  # type: ignore[misc]
        return result is not None
    except Exception:
        logger.warning("Failed to wait for a task-ready notification from Redis", exc_info=True)
        return False
