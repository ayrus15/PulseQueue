"""Repository methods for tasks and their attempts.

Transaction boundaries live here, not in the API or worker layer: a
caller invokes one repository method and either gets a result or lets a
domain exception propagate - it never manages a commit/rollback itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.domain.errors import TaskNotFoundError
from pulsequeue.domain.models import AttemptOutcome, TaskStatus
from pulsequeue.domain.stateMachine import TaskEvent, applyTransition
from pulsequeue.persistence.models import TaskAttemptRecord, TaskRecord


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

    async def claimNextTasks(
        self, workerId: str, leaseSeconds: int, batchSize: int = 1
    ) -> list[TaskRecord]:
        """Atomically claim up to ``batchSize`` eligible tasks for ``workerId``.

        ``FOR UPDATE SKIP LOCKED`` is what makes this safe under concurrent
        workers: a second worker's concurrent call simply skips rows already
        locked by the first, so no two workers can claim the same row - see
        ADR 0003.
        """
        now = datetime.now(UTC)
        statement = (
            select(TaskRecord)
            .where(TaskRecord.status == TaskStatus.QUEUED.value)
            .where(TaskRecord.scheduledAt <= now)
            .order_by(TaskRecord.scheduledAt, TaskRecord.createdAt)
            .limit(batchSize)
            .with_for_update(skip_locked=True)
        )
        records = list((await self._session.execute(statement)).scalars().all())
        for record in records:
            record.status = applyTransition(TaskStatus(record.status), TaskEvent.WORKER_CLAIMED)
            record.leaseOwner = workerId
            record.leaseExpiresAt = now + timedelta(seconds=leaseSeconds)
            record.startedAt = record.startedAt or now
            record.attemptCount += 1
            record.updatedAt = now
        await self._session.commit()
        return records

    async def recordSuccess(
        self, task: TaskRecord, result: dict[str, object], completedAt: datetime
    ) -> None:
        task.status = applyTransition(TaskStatus(task.status), TaskEvent.HANDLER_SUCCEEDED)
        task.result = result
        task.completedAt = completedAt
        task.updatedAt = completedAt
        task.leaseOwner = None
        task.leaseExpiresAt = None
        await self._session.commit()

    async def recordFailure(
        self, task: TaskRecord, errorCode: str, errorMessage: str, failedAt: datetime
    ) -> AttemptOutcome:
        """Move ``task`` back to ``queued`` if attempts remain, else
        ``dead_letter``. Returns which happened, for the caller to record on
        the attempt row.

        Phase 2 simplification: a retried task is requeued immediately
        (``scheduledAt = failedAt``) with no backoff delay, and every
        failure is treated as retryable - Phase 3 adds the exponential
        backoff calculation and permanent-vs-retryable error
        classification (ADR 0004).
        """
        task.lastErrorCode = errorCode
        task.lastErrorMessage = errorMessage
        task.updatedAt = failedAt
        task.leaseOwner = None
        task.leaseExpiresAt = None

        if task.attemptCount >= task.maxAttempts:
            task.status = applyTransition(TaskStatus(task.status), TaskEvent.RETRY_LIMIT_EXHAUSTED)
            outcome = AttemptOutcome.DEAD_LETTER
        else:
            task.status = applyTransition(
                TaskStatus(task.status), TaskEvent.RETRYABLE_FAILURE_WITH_ATTEMPTS_REMAINING
            )
            task.scheduledAt = failedAt
            outcome = AttemptOutcome.RETRIED

        await self._session.commit()
        return outcome


class TaskAttemptRepository:
    """Owns all SQL for the ``task_attempts`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def startAttempt(
        self, taskId: uuid.UUID, attemptNumber: int, workerId: str, startedAt: datetime
    ) -> TaskAttemptRecord:
        attempt = TaskAttemptRecord(
            id=uuid.uuid4(),
            taskId=taskId,
            attemptNumber=attemptNumber,
            workerId=workerId,
            startedAt=startedAt,
        )
        self._session.add(attempt)
        await self._session.commit()
        return attempt

    async def finishAttempt(
        self,
        attempt: TaskAttemptRecord,
        outcome: AttemptOutcome,
        endedAt: datetime,
        errorCode: str | None = None,
        errorMessage: str | None = None,
    ) -> None:
        attempt.endedAt = endedAt
        attempt.outcome = outcome.value
        attempt.errorCode = errorCode
        attempt.errorMessage = errorMessage
        attempt.durationMs = int((endedAt - attempt.startedAt).total_seconds() * 1000)
        await self._session.commit()
