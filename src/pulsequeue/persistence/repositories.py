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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.domain.errors import IdempotencyConflictError, TaskNotFoundError
from pulsequeue.domain.idempotency import computeRequestFingerprint
from pulsequeue.domain.models import AttemptOutcome, TaskStatus
from pulsequeue.domain.retryPolicy import computeRetryDelaySeconds
from pulsequeue.domain.stateMachine import TaskEvent, applyTransition
from pulsequeue.persistence.models import IdempotencyRecord, TaskAttemptRecord, TaskRecord

DEFAULT_IDEMPOTENCY_SCOPE = "default"
"""Until authentication exists, every client shares this scope (ADR 0004) -
the column already supports per-client scoping without a schema change."""


@dataclass(frozen=True, slots=True)
class NewTaskInput:
    taskType: str
    payload: dict[str, object]
    maxAttempts: int
    correlationId: str


@dataclass(frozen=True, slots=True)
class TaskCreationResult:
    task: TaskRecord
    wasCreated: bool
    """False when an idempotency key matched an existing request and
    ``task`` is that original task, not a new one."""


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

    async def createTaskIdempotently(
        self,
        newTask: NewTaskInput,
        idempotencyKey: str,
        scope: str = DEFAULT_IDEMPOTENCY_SCOPE,
    ) -> TaskCreationResult:
        """Create a task guarded by an idempotency key.

        The task and its idempotency record are inserted in the same
        transaction. If ``(scope, idempotencyKey)`` already exists
        (enforced by a PostgreSQL unique constraint, not just this check
        - see ADR 0004), a matching fingerprint returns the *original*
        task instead of creating a new one, and a mismatched fingerprint
        raises IdempotencyConflictError. This makes concurrent duplicate
        submissions resolve to exactly one task: only one request's
        INSERT can win the unique constraint, and the other's
        IntegrityError is handled the same way a pre-existing row would
        be.
        """
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
        fingerprint = computeRequestFingerprint(
            newTask.taskType, newTask.payload, newTask.maxAttempts
        )
        idempotencyRecord = IdempotencyRecord(
            id=uuid.uuid4(),
            scope=scope,
            idempotencyKey=idempotencyKey,
            requestFingerprint=fingerprint,
            taskId=record.id,
            createdAt=now,
        )
        try:
            self._session.add(record)
            # Flushed separately so the task row exists before the
            # idempotency row's foreign key is checked, regardless of
            # unit-of-work insert ordering between the two unrelated models.
            await self._session.flush()
            self._session.add(idempotencyRecord)
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            return await self._resolveIdempotencyConflict(scope, idempotencyKey, fingerprint)
        return TaskCreationResult(task=record, wasCreated=True)

    async def _resolveIdempotencyConflict(
        self, scope: str, idempotencyKey: str, fingerprint: str
    ) -> TaskCreationResult:
        existing = await self._session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.idempotencyKey == idempotencyKey,
            )
        )
        if existing is None:
            # The row we collided with is gone by the time we re-read it -
            # extremely unlikely (nothing deletes idempotency records), but
            # safer to surface clearly than to retry silently forever.
            raise IdempotencyConflictError(idempotencyKey)
        if existing.requestFingerprint != fingerprint:
            raise IdempotencyConflictError(idempotencyKey)
        existingTask = await self.getTaskById(existing.taskId)
        return TaskCreationResult(task=existingTask, wasCreated=False)

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

    async def findExpiredLeaseTasks(self, now: datetime, batchSize: int = 50) -> list[TaskRecord]:
        """Tasks stuck ``running`` past their lease - the worker that
        claimed them is presumed dead (ADR 0003). ``FOR UPDATE SKIP LOCKED``
        so concurrent recovery passes never double-process the same row.
        """
        statement = (
            select(TaskRecord)
            .where(TaskRecord.status == TaskStatus.RUNNING.value)
            .where(TaskRecord.leaseExpiresAt < now)
            .limit(batchSize)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def applyLeaseExpired(self, task: TaskRecord, now: datetime) -> None:
        """Return a task whose lease expired to ``queued``, immediately
        eligible (no backoff - the task itself never failed, its worker
        just vanished).
        """
        task.status = applyTransition(TaskStatus(task.status), TaskEvent.LEASE_EXPIRED)
        task.leaseOwner = None
        task.leaseExpiresAt = None
        task.scheduledAt = now
        task.updatedAt = now
        await self._session.commit()

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
        self,
        task: TaskRecord,
        errorCode: str,
        errorMessage: str,
        failedAt: datetime,
        isPermanent: bool,
        baseDelaySeconds: float,
        maxDelaySeconds: float,
    ) -> AttemptOutcome:
        """Apply a failed attempt's consequence and return which one:

        - ``isPermanent`` -> ``failed``, regardless of attempts remaining
          (ADR 0004: a handler raises PermanentTaskError for this).
        - attempts exhausted -> ``dead_letter``.
        - otherwise -> back to ``queued``, with bounded exponential
          backoff plus jitter (``domain/retryPolicy.py``) before it's
          eligible to be claimed again.
        """
        task.lastErrorCode = errorCode
        task.lastErrorMessage = errorMessage
        task.updatedAt = failedAt
        task.leaseOwner = None
        task.leaseExpiresAt = None

        if isPermanent:
            task.status = applyTransition(TaskStatus(task.status), TaskEvent.PERMANENT_FAILURE)
            outcome = AttemptOutcome.FAILED
        elif task.attemptCount >= task.maxAttempts:
            task.status = applyTransition(TaskStatus(task.status), TaskEvent.RETRY_LIMIT_EXHAUSTED)
            outcome = AttemptOutcome.DEAD_LETTER
        else:
            task.status = applyTransition(
                TaskStatus(task.status), TaskEvent.RETRYABLE_FAILURE_WITH_ATTEMPTS_REMAINING
            )
            delaySeconds = computeRetryDelaySeconds(
                nextAttemptNumber=task.attemptCount + 1,
                baseDelaySeconds=baseDelaySeconds,
                maxDelaySeconds=maxDelaySeconds,
            )
            task.scheduledAt = failedAt + timedelta(seconds=delaySeconds)
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

    async def closeOrphanedAttempt(
        self, taskId: uuid.UUID, attemptNumber: int, endedAt: datetime
    ) -> None:
        """Close out the still-open attempt row for a task whose lease
        expired - the worker that opened it never got to call
        ``finishAttempt`` itself. A no-op if there isn't one (e.g. the
        worker finished and committed just as the lease was being
        recovered) - recovery never overwrites a real outcome.
        """
        attempt = await self._session.scalar(
            select(TaskAttemptRecord).where(
                TaskAttemptRecord.taskId == taskId,
                TaskAttemptRecord.attemptNumber == attemptNumber,
                TaskAttemptRecord.outcome.is_(None),
            )
        )
        if attempt is None:
            return
        await self.finishAttempt(
            attempt,
            AttemptOutcome.LEASE_EXPIRED,
            endedAt=endedAt,
            errorMessage="Worker lease expired before the attempt finished",
        )
