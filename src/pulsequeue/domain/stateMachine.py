"""The task state machine: every allowed transition, enforced explicitly.

See docs/architecture.md for the state diagram this table implements, and
ADR 0003/0004 for why each transition exists. Nothing outside this module
should decide whether a transition is legal.
"""

from __future__ import annotations

from enum import StrEnum

from pulsequeue.domain.errors import InvalidStateTransitionError
from pulsequeue.domain.models import TaskStatus


class TaskEvent(StrEnum):
    """Events that can move a task from one status to another."""

    WORKER_CLAIMED = "worker_claimed"
    CANCEL_ACCEPTED = "cancel_accepted"
    HANDLER_SUCCEEDED = "handler_succeeded"
    RETRYABLE_FAILURE_WITH_ATTEMPTS_REMAINING = "retryable_failure_with_attempts_remaining"
    PERMANENT_FAILURE = "permanent_failure"
    RETRY_LIMIT_EXHAUSTED = "retry_limit_exhausted"
    LEASE_EXPIRED = "lease_expired"
    ADMIN_REQUEUE = "admin_requeue"


_TRANSITIONS: dict[tuple[TaskStatus, TaskEvent], TaskStatus] = {
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


def applyTransition(currentStatus: TaskStatus, event: TaskEvent) -> TaskStatus:
    """Return the next status for ``event`` applied to ``currentStatus``.

    Raises InvalidStateTransitionError if the pair isn't in the table above -
    including every transition out of a terminal status, and every event
    that doesn't apply to the current status.
    """
    nextStatus = _TRANSITIONS.get((currentStatus, event))
    if nextStatus is None:
        raise InvalidStateTransitionError(currentStatus, event)
    return nextStatus


def isAllowedTransition(currentStatus: TaskStatus, event: TaskEvent) -> bool:
    return (currentStatus, event) in _TRANSITIONS
