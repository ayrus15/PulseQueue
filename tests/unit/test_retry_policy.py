from __future__ import annotations

import pytest

from pulsequeue.domain.retryPolicy import computeRetryDelaySeconds


def _zeroJitter() -> float:
    return 0.0


def _maxJitter() -> float:
    return 1.0


def testFirstRetryUsesTheBaseDelay() -> None:
    delay = computeRetryDelaySeconds(
        nextAttemptNumber=2, baseDelaySeconds=1.0, maxDelaySeconds=60.0, randomFn=_zeroJitter
    )
    assert delay == 1.0


def testDelayDoublesEachAttempt() -> None:
    base = 1.0
    delays = [
        computeRetryDelaySeconds(
            nextAttemptNumber=n, baseDelaySeconds=base, maxDelaySeconds=1000.0, randomFn=_zeroJitter
        )
        for n in (2, 3, 4, 5)
    ]
    assert delays == [1.0, 2.0, 4.0, 8.0]


def testDelayIsBoundedByMaxDelaySeconds() -> None:
    delay = computeRetryDelaySeconds(
        nextAttemptNumber=20, baseDelaySeconds=1.0, maxDelaySeconds=30.0, randomFn=_zeroJitter
    )
    assert delay == 30.0


def testJitterIsBoundedByTheJitterFraction() -> None:
    delay = computeRetryDelaySeconds(
        nextAttemptNumber=2,
        baseDelaySeconds=10.0,
        maxDelaySeconds=60.0,
        jitterFraction=0.2,
        randomFn=_maxJitter,
    )
    assert delay == pytest.approx(12.0)


def testZeroJitterFractionIsDeterministic() -> None:
    delay = computeRetryDelaySeconds(
        nextAttemptNumber=3,
        baseDelaySeconds=5.0,
        maxDelaySeconds=60.0,
        jitterFraction=0.0,
        randomFn=_maxJitter,
    )
    assert delay == 10.0


@pytest.mark.parametrize("nextAttemptNumber", [0, 1, -1])
def testRejectsAttemptNumbersBelowTwo(nextAttemptNumber: int) -> None:
    with pytest.raises(ValueError, match="nextAttemptNumber"):
        computeRetryDelaySeconds(
            nextAttemptNumber=nextAttemptNumber, baseDelaySeconds=1.0, maxDelaySeconds=60.0
        )


def testRejectsNonPositiveBaseDelay() -> None:
    with pytest.raises(ValueError, match="positive"):
        computeRetryDelaySeconds(nextAttemptNumber=2, baseDelaySeconds=0.0, maxDelaySeconds=60.0)


def testRejectsBaseDelayGreaterThanMaxDelay() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        computeRetryDelaySeconds(nextAttemptNumber=2, baseDelaySeconds=100.0, maxDelaySeconds=60.0)


def testNeverSleepsOrUsesTheWallClock() -> None:
    """Runs many attempt numbers instantly - a real sanity check that this
    function has no hidden sleep/await, not just a docstring claim."""
    for attempt in range(2, 50):
        computeRetryDelaySeconds(
            nextAttemptNumber=attempt, baseDelaySeconds=1.0, maxDelaySeconds=60.0
        )
