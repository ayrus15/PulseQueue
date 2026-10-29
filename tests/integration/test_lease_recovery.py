"""Integration tests for lease-expiry recovery against real PostgreSQL.

A task whose lease already expired is simulated via a negative
``leaseSeconds`` on claim - the resulting ``leaseExpiresAt`` is
immediately in the past, standing in for "a worker claimed this, then
died before finishing."
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.domain.models import AttemptOutcome, TaskStatus
from pulsequeue.persistence.repositories import NewTaskInput, TaskAttemptRepository, TaskRepository
from pulsequeue.recovery.leaseRecovery import recoverExpiredLeases


async def _createAndAbandonClaim(dbSession: AsyncSession) -> tuple[object, object]:
    taskRepository = TaskRepository(dbSession)
    attemptRepository = TaskAttemptRepository(dbSession)

    task = await taskRepository.createTask(
        NewTaskInput(
            taskType="generateReport",
            payload={"reportName": "x", "periodDays": 1},
            maxAttempts=4,
            correlationId="corr-recovery",
        )
    )
    claimed = await taskRepository.claimNextTasks(workerId="dead-worker", leaseSeconds=-10)
    assert claimed  # sanity: the claim itself succeeded before "dying"

    attempt = await attemptRepository.startAttempt(
        taskId=task.id,
        attemptNumber=claimed[0].attemptCount,
        workerId="dead-worker",
        startedAt=datetime.now(UTC),
    )
    return task, attempt


async def testRecoverExpiredLeasesRequeuesAnAbandonedTask(dbSession: AsyncSession) -> None:
    task, _attempt = await _createAndAbandonClaim(dbSession)

    recoveredIds = await recoverExpiredLeases(dbSession, datetime.now(UTC))

    assert task.id in recoveredIds
    refreshed = await TaskRepository(dbSession).getTaskById(task.id)
    assert refreshed.status == TaskStatus.QUEUED.value
    assert refreshed.leaseOwner is None
    assert refreshed.leaseExpiresAt is None


async def testRecoverExpiredLeasesClosesTheOrphanedAttempt(dbSession: AsyncSession) -> None:
    task, attempt = await _createAndAbandonClaim(dbSession)

    await recoverExpiredLeases(dbSession, datetime.now(UTC))

    await dbSession.refresh(attempt)
    assert attempt.outcome == AttemptOutcome.LEASE_EXPIRED.value
    assert attempt.endedAt is not None


async def testRecoverExpiredLeasesIsANoOpWithNothingExpired(dbSession: AsyncSession) -> None:
    taskRepository = TaskRepository(dbSession)
    await taskRepository.createTask(
        NewTaskInput(
            taskType="generateReport",
            payload={"reportName": "x", "periodDays": 1},
            maxAttempts=4,
            correlationId="corr-not-stuck",
        )
    )
    # Still queued, never claimed - nothing for recovery to find.
    recoveredIds = await recoverExpiredLeases(dbSession, datetime.now(UTC))
    assert recoveredIds == []


async def testRecoveredTaskCanBeClaimedAndSucceedNormally(dbSession: AsyncSession) -> None:
    task, _attempt = await _createAndAbandonClaim(dbSession)
    await recoverExpiredLeases(dbSession, datetime.now(UTC))

    taskRepository = TaskRepository(dbSession)
    reClaimed = await taskRepository.claimNextTasks(workerId="live-worker", leaseSeconds=30)

    assert [t.id for t in reClaimed] == [task.id]
    assert reClaimed[0].attemptCount == 2  # the abandoned attempt plus this one
