"""Exhaustive coverage of the task state machine: every allowed transition,
and every status/event pair that must be rejected.
"""

from __future__ import annotations

import itertools

import pytest

from pulsequeue.domain.errors import InvalidStateTransitionError
from pulsequeue.domain.models import TaskStatus
from pulsequeue.domain.stateMachine import TaskEvent, applyTransition, isAllowedTransition

# The complete set of legal transitions, independent of stateMachine.py's own
# table - this is what makes the test meaningful rather than circular.
ALLOWED_TRANSITIONS: dict[tuple[TaskStatus, TaskEvent], TaskStatus] = {
    (TaskStatus.QUEUED, TaskEvent.WORKER_CLAIMED): TaskStatus.RUNNING,
    (TaskStatus.QUEUED, TaskEvent.CANCEL_ACCEPTED): TaskStatus.CANCELLED,
    (TaskStatus.RUNNING, TaskEvent.HANDLER_SUCCEEDED): TaskStatus.SUCCEEDED,
    (
        TaskStatus.RUNNING,
        TaskEvent.RETRYABLE_FAILURE_WITH_ATTEMPTS_REMAINING,
    ): TaskStatus.QUEUED,
    (TaskStatus.RUNNING, TaskEvent.PERMANENT_FAILURE): TaskStatus.FAILED,
    (TaskStatus.RUNNING, TaskEvent.RETRY_LIMIT_EXHAUSTED): TaskStatus.DEAD_LETTER,
    (TaskStatus.RUNNING, TaskEvent.LEASE_EXPIRED): TaskStatus.QUEUED,
    (TaskStatus.DEAD_LETTER, TaskEvent.ADMIN_REQUEUE): TaskStatus.QUEUED,
}


@pytest.mark.parametrize(("fromStatus", "event", "toStatus"), [
    (fromStatus, event, toStatus) for (fromStatus, event), toStatus in ALLOWED_TRANSITIONS.items()
])
def testAllowedTransitionsSucceed(
    fromStatus: TaskStatus, event: TaskEvent, toStatus: TaskStatus
) -> None:
    assert applyTransition(fromStatus, event) == toStatus
    assert isAllowedTransition(fromStatus, event) is True


@pytest.mark.parametrize(
    ("fromStatus", "event"),
    [
        pair
        for pair in itertools.product(TaskStatus, TaskEvent)
        if pair not in ALLOWED_TRANSITIONS
    ],
)
def testDisallowedTransitionsRaise(fromStatus: TaskStatus, event: TaskEvent) -> None:
    assert isAllowedTransition(fromStatus, event) is False
    with pytest.raises(InvalidStateTransitionError) as excInfo:
        applyTransition(fromStatus, event)
    assert excInfo.value.currentStatus == fromStatus
    assert excInfo.value.event == event


def testEveryTerminalStatusHasNoOutgoingOrdinaryTransition() -> None:
    for terminalStatus in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        for event in TaskEvent:
            assert isAllowedTransition(terminalStatus, event) is False


def testAllAllowedTransitionsAreCoveredByTheStateMachine() -> None:
    """Sanity check that this test's reference table matches the full set
    the implementation allows - if someone adds a transition to
    stateMachine.py without updating this test, this fails."""
    implementationAllowed = {
        pair for pair in itertools.product(TaskStatus, TaskEvent) if isAllowedTransition(*pair)
    }
    assert implementationAllowed == set(ALLOWED_TRANSITIONS.keys())
