"""Repository methods for persisting and retrieving tasks.

Transaction boundaries live here, not in the API layer: a route handler
calls one repository method and either gets a result or lets a domain
exception propagate - it never manages a commit/rollback itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.domain.errors import TaskNotFoundError
from pulsequeue.domain.models import TaskStatus
from pulsequeue.persistence.models import TaskRecord


@dataclass(frozen=True, slots=True)
class NewTaskInput:
    taskType: str
    payload: dict[str, object]
    maxAttempts: int
    correlationId: str


class TaskRepository:
    """Owns all SQL for the ``tasks`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def createTask(self, newTask: NewTaskInput) -> TaskRecord:
        now = datetime.now(UTC)
        record = TaskRecord(
            id=uuid.uuid4(),
            taskType=newTask.taskType,
            payload=newTask.payload,
            status=TaskStatus.QUEUED.value,
            priority=0,
            attemptCount=0,
            maxAttempts=newTask.maxAttempts,
            createdAt=now,
            scheduledAt=now,
            updatedAt=now,
            correlationId=newTask.correlationId,
        )
        self._session.add(record)
        await self._session.commit()
        return record

    async def getTaskById(self, taskId: uuid.UUID) -> TaskRecord:
        record = await self._session.get(TaskRecord, taskId)
        if record is None:
            raise TaskNotFoundError(taskId)
        return record
