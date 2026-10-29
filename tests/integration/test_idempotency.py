"""Integration tests for idempotent task creation against real
PostgreSQL - including a genuine concurrency test, per PROJECT_PLAN.md
FR7: "Add concurrency tests that submit duplicate requests simultaneously."
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from pulsequeue.domain.errors import IdempotencyConflictError
from pulsequeue.persistence.database import createSessionFactory
from pulsequeue.persistence.repositories import NewTaskInput, TaskRepository


def _sampleTask(reportName: str = "weekly") -> NewTaskInput:
    return NewTaskInput(
        taskType="generateReport",
        payload={"reportName": reportName, "periodDays": 7},
        maxAttempts=4,
        correlationId="corr-idem",
    )


async def testSameKeyAndFingerprintReturnsTheOriginalTask(dbSession: AsyncSession) -> None:
    repository = TaskRepository(dbSession)
    first = await repository.createTaskIdempotently(_sampleTask(), idempotencyKey="key-1")
    second = await repository.createTaskIdempotently(_sampleTask(), idempotencyKey="key-1")

    assert first.wasCreated is True
    assert second.wasCreated is False
    assert second.task.id == first.task.id


async def testSameKeyWithDifferentPayloadRaisesConflict(dbSession: AsyncSession) -> None:
    repository = TaskRepository(dbSession)
    await repository.createTaskIdempotently(_sampleTask("weekly"), idempotencyKey="key-2")

    with pytest.raises(IdempotencyConflictError):
        await repository.createTaskIdempotently(_sampleTask("monthly"), idempotencyKey="key-2")


async def testDifferentKeysCreateDifferentTasks(dbSession: AsyncSession) -> None:
    repository = TaskRepository(dbSession)
    first = await repository.createTaskIdempotently(_sampleTask(), idempotencyKey="key-3")
    second = await repository.createTaskIdempotently(_sampleTask(), idempotencyKey="key-4")

    assert first.task.id != second.task.id


async def testConcurrentDuplicateSubmissionsCreateExactlyOneTask(
    dbSession: AsyncSession, engine: AsyncEngine
) -> None:
    sessionFactory = createSessionFactory(engine)

    async def submit() -> str:
        async with sessionFactory() as session:
            result = await TaskRepository(session).createTaskIdempotently(
                _sampleTask(), idempotencyKey="concurrent-key"
            )
            return str(result.task.id)

    taskIds = await asyncio.gather(submit(), submit(), submit())

    assert len(set(taskIds)) == 1
