"""A minimal fixed-window rate limiter backed by Redis.

Disabled by default (``PULSEQUEUE_RATE_LIMIT_ENABLED=false``) - this is
a demo/local-deployment project (PROJECT_PLAN.md's Phase 4 task says
"if appropriate"), and a shared single-instance limit isn't the right
default for local development or the test suite. An operator exposing
this beyond localhost should turn it on.

Unlike the wake-up notifications in queueing/redisQueue.py, this fails
*open*, not closed-but-harmless: if Redis is unreachable, requests are
allowed rather than rejected, since a security control available, by
design (ADR 0002), should never become a way to take the whole API
down just by being unreachable.
"""

from __future__ import annotations

import logging
import time

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


async def checkRateLimit(redisClient: Redis, key: str, limit: int, windowSeconds: int) -> bool:
    """Returns True if the caller identified by ``key`` may proceed.

    A fixed window (not sliding/token-bucket) - simple, and precise
    enough for the "basic abuse guard on a local deployment" this is
    meant to be, not a production-grade limiter.
    """
    windowIndex = int(time.time() // windowSeconds)
    bucketKey = f"pulsequeue:ratelimit:{key}:{windowIndex}"
    try:
        count = await redisClient.incr(bucketKey)
        if count == 1:
            await redisClient.expire(bucketKey, windowSeconds)
        return bool(count <= limit)
    except Exception:
        logger.warning("Rate limit check failed open (Redis unreachable)", exc_info=True)
        return True
