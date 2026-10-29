"""Domain-level exceptions.

These carry no HTTP knowledge (no status codes, no response bodies) -
`api/errorHandlers.py` is the only place that translates them into HTTP
responses. Keeping that mapping in one place is what lets the API never
leak a raw stack trace: every exception that can escape a route handler
either is one of these, or is a bug.
"""

from __future__ import annotations


class PulseQueueError(Exception):
    """Base class for all domain errors raised by PulseQueue."""


class ValidationError(PulseQueueError):
    """The request was well-formed JSON but failed domain validation.

    Permanent: never retried.
    """


class UnsupportedTaskTypeError(PulseQueueError):
    """The requested task type is not in the registered handler allowlist.

    Permanent: never retried.
    """

    def __init__(self, taskType: str) -> None:
        self.taskType = taskType
        super().__init__(f"Unsupported task type: {taskType!r}")


class TaskNotFoundError(PulseQueueError):
    """No task exists with the requested ID."""

    def __init__(self, taskId: object) -> None:
        self.taskId = taskId
        super().__init__(f"Task not found: {taskId!r}")


class InvalidStateTransitionError(PulseQueueError):
    """The requested state transition is not allowed from the current state."""

    def __init__(self, currentStatus: object, event: object) -> None:
        self.currentStatus = currentStatus
        self.event = event
        super().__init__(f"Cannot apply event {event!r} to task in status {currentStatus!r}")


class IdempotencyConflictError(PulseQueueError):
    """An idempotency key was reused with a different logical request."""

    def __init__(self, idempotencyKey: str) -> None:
        self.idempotencyKey = idempotencyKey
        super().__init__(f"Idempotency key reused with a different request: {idempotencyKey!r}")
