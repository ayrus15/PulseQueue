"""Bounded exponential backoff with jitter (ADR 0004).

A pure function: no sleeping, no wall-clock dependency. Tests call it
directly with whatever attempt numbers and config they want, instead of
waiting through real delays.
"""

from __future__ import annotations

import random
from collections.abc import Callable

DEFAULT_JITTER_FRACTION = 0.2


def computeRetryDelaySeconds(
    nextAttemptNumber: int,
    baseDelaySeconds: float,
    maxDelaySeconds: float,
    jitterFraction: float = DEFAULT_JITTER_FRACTION,
    randomFn: Callable[[], float] = random.random,
) -> float:
    """Delay before ``nextAttemptNumber`` (>= 2; attempt 1 never waits).

    ``delay = min(maxDelaySeconds, baseDelaySeconds * 2 ** (nextAttemptNumber - 2))``,
    plus jitter in ``[0, delay * jitterFraction)``.

    ``randomFn`` takes no arguments and returns a float in [0, 1) - inject
    a deterministic one in tests instead of patching the `random` module.
    """
    if nextAttemptNumber < 2:
        raise ValueError(f"nextAttemptNumber must be >= 2, got {nextAttemptNumber}")
    if baseDelaySeconds <= 0 or maxDelaySeconds <= 0:
        raise ValueError("baseDelaySeconds and maxDelaySeconds must be positive")
    if baseDelaySeconds > maxDelaySeconds:
        raise ValueError("baseDelaySeconds cannot exceed maxDelaySeconds")

    exponent = nextAttemptNumber - 2
    rawDelay = baseDelaySeconds * (2.0**exponent)
    boundedDelay = min(maxDelaySeconds, rawDelay)

    jitter = randomFn() * boundedDelay * jitterFraction
    return boundedDelay + jitter
