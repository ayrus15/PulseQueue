"""Integration tests for TaskRepository's claim/success/failure methods
and TaskAttemptRepository, against a real PostgreSQL database.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from pulsequeue.domain.models import AttemptOutcome, TaskStatus
from pulsequeue.persistence.database import createSessionFactory
from pulsequeue.persistence.models import TaskRecord
from pulsequeue.persistence.repositories import NewTaskInput, TaskAttemptRepository, TaskRepository


async def _createQueuedTask(session: AsyncSession, maxAttempts: int = 4) -> TaskRecord:
    repository = TaskRepository(session)
    return await repository.createTask(
        NewTaskInput(
            taskType="generateReport",
            payload={"reportName": "x", "periodDays": 1},
            maxAttempts=maxAttempts,
            correlationId="test-correlation",
        )
    )


async def testClaimNextTasksClaimsAQueuedTask(dbSession: AsyncSession) -> None:
    task = await _createQueuedTask(dbSession)
    repository = TaskRepository(dbSession)

    claimed = await repository.claimNextTasks(workerId="worker-1", leaseSeconds=30)

    assert [t.id for t in claimed] == [task.id]
    assert claimed[0].status == TaskStatus.RUNNING.value
    assert claimed[0].leaseOwner == "worker-1"
    assert claimed[0].attemptCount == 1
    assert claimed[0].leaseExpiresAt is not None


async def testClaimNextTasksSkipsAlreadyClaimedTasks(dbSession: AsyncSession) -> None:
    await _createQueuedTask(dbSession)
    repository = TaskRepository(dbSession)

    firstClaim = await repository.claimNextTasks(workerId="worker-1", leaseSeconds=30)
    secondClaim = await repository.claimNextTasks(workerId="worker-2", leaseSeconds=30)

    assert len(firstClaim) == 1
    assert secondClaim == []


async def testConcurrentWorkersNeverClaimTheSameTask(
    dbSession: AsyncSession, engine: AsyncEngine
) -> None:
    await _createQueuedTask(dbSession)
    sessionFactory = createSessionFactory(engine)

    async def claimWith(workerId: str) -> list[TaskRecord]:
        async with sessionFactory() as session:
            return await TaskRepository(session).claimNextTasks(workerId=workerId, leaseSeconds=30)

    resultA, resultB = await asyncio.gather(claimWith("worker-a"), claimWith("worker-b"))
    totalClaimed = len(resultA) + len(resultB)
    assert totalClaimed == 1


async def testRecordSuccessMarksTaskSucceeded(dbSession: AsyncSession) -> None:
    task = await _createQueuedTask(dbSession)
    repository = TaskRepository(dbSession)
    await repository.claimNextTasks(workerId="worker-1", leaseSeconds=30)

    completedAt = datetime.now(UTC)
    await repository.recordSuccess(task, result={"ok": True}, completedAt=completedAt)

    refreshed = await repository.getTaskById(task.id)
    assert refreshed.status == TaskStatus.SUCCEEDED.value
    assert refreshed.result == {"ok": True}
    assert refreshed.leaseOwner is None


async def testRecordFailureRequeuesWhenAttemptsRemain(dbSession: AsyncSession) -> None:
    task = await _createQueuedTask(dbSession, maxAttempts=4)
    repository = TaskRepository(dbSession)
    await repository.claimNextTasks(workerId="worker-1", leaseSeconds=30)

    outcome = await repository.recordFailure(
        task, errorCode="RuntimeError", errorMessage="boom", failedAt=datetime.now(UTC)
    )

    assert outcome == AttemptOutcome.RETRIED
    refreshed = await repository.getTaskById(task.id)
    assert refreshed.status == TaskStatus.QUEUED.value
    assert refreshed.lastErrorCode == "RuntimeError"
    assert refreshed.leaseOwner is None


async def testRecordFailureDeadLettersAfterExhaustingAttempts(dbSession: AsyncSession) -> None:
    task = await _createQueuedTask(dbSession, maxAttempts=1)
    repository = TaskRepository(dbSession)
    await repository.claimNextTasks(workerId="worker-1", leaseSeconds=30)

    outcome = await repository.recordFailure(
        task, errorCode="RuntimeError", errorMessage="boom", failedAt=datetime.now(UTC)
    )

    assert outcome == AttemptOutcome.DEAD_LETTER
    refreshed = await repository.getTaskById(task.id)
    assert refreshed.status == TaskStatus.DEAD_LETTER.value


async def testAttemptRepositoryRecordsStartAndFinish(dbSession: AsyncSession) -> None:
    task = await _createQueuedTask(dbSession)
    taskRepository = TaskRepository(dbSession)
    await taskRepository.claimNextTasks(workerId="worker-1", leaseSeconds=30)

    attemptRepository = TaskAttemptRepository(dbSession)
    startedAt = datetime.now(UTC)
    attempt = await attemptRepository.startAttempt(
        taskId=task.id, attemptNumber=1, workerId="worker-1", startedAt=startedAt
    )
    assert attempt.outcome is None

    endedAt = datetime.now(UTC)
    await attemptRepository.finishAttempt(attempt, AttemptOutcome.SUCCEEDED, endedAt=endedAt)

    assert attempt.outcome == AttemptOutcome.SUCCEEDED.value
    assert attempt.durationMs is not None
    assert attempt.durationMs >= 0


async def testAttemptNumberMustBeUniquePerTask(dbSession: AsyncSession) -> None:
    from sqlalchemy.exc import IntegrityError

    task = await _createQueuedTask(dbSession)
    attemptRepository = TaskAttemptRepository(dbSession)
    now = datetime.now(UTC)
    await attemptRepository.startAttempt(
        task.id, attemptNumber=1, workerId="worker-1", startedAt=now
    )

    with pytest.raises(IntegrityError):
        await attemptRepository.startAttempt(
            task.id, attemptNumber=1, workerId="worker-2", startedAt=now
        )
