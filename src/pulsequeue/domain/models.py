"""Core domain vocabulary shared across the domain, persistence, and API layers."""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    """The six states a task can be in. See docs/architecture.md for the diagram."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
)
"""Statuses with no outgoing ordinary transition (dead_letter can still be requeued)."""
