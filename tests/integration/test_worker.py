"""End-to-end worker tests against a real PostgreSQL database: a task
submitted the same way the API submits it, actually claimed and
executed by a real Worker instance.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from pulsequeue.domain.models import TaskStatus
from pulsequeue.persistence.database import createSessionFactory
from pulsequeue.persistence.repositories import NewTaskInput, TaskRepository
from pulsequeue.workers.registry import buildHandlerRegistry
from pulsequeue.workers.worker import Worker


class _NullRedis:
    """A Redis stand-in that always reports "no notification" - the
    worker falls back to its (irrelevant, in these tests) poll interval
    regardless, per ADR 0002, so this never affects correctness.
    """

    async def rpush(self, *args: object, **kwargs: object) -> int:
        return 1

    async def blpop(self, *args: object, **kwargs: object) -> None:
        return None


@pytest_asyncio.fixture
async def worker(engine: AsyncEngine, tmp_path: Path) -> AsyncIterator[Worker]:
    sessionFactory = createSessionFactory(engine)
    handlerRegistry = buildHandlerRegistry(tmp_path)
    yield Worker(
        workerId="test-worker",
        sessionFactory=sessionFactory,
        redisClient=_NullRedis(),  # type: ignore[arg-type]
        handlerRegistry=handlerRegistry,
        leaseSeconds=30,
        pollIntervalSeconds=1.0,
        concurrency=1,
    )


async def testWorkerClaimsAndSucceedsASimpleTask(engine: AsyncEngine, worker: Worker) -> None:
    sessionFactory = createSessionFactory(engine)
    async with sessionFactory() as session:
        task = await TaskRepository(session).createTask(
            NewTaskInput(
                taskType="calculateMetrics",
                payload={"metricName": "latency", "values": [1.0, 2.0, 3.0]},
                maxAttempts=3,
                correlationId="corr-1",
            )
        )

    claimedSomething = await worker.claimAndProcessOne()
    assert claimedSomething is True

    async with sessionFactory() as session:
        refreshed = await TaskRepository(session).getTaskById(task.id)
    assert refreshed.status == TaskStatus.SUCCEEDED.value
    assert refreshed.result == {
        "metricName": "latency",
        "count": 3,
        "mean": 2.0,
        "min": 1.0,
        "max": 3.0,
    }
    assert refreshed.attemptCount == 1


async def testWorkerRequeuesOnFailureThenDeadLettersAfterExhaustion(
    engine: AsyncEngine, worker: Worker
) -> None:
    sessionFactory = createSessionFactory(engine)
    async with sessionFactory() as session:
        task = await TaskRepository(session).createTask(
            NewTaskInput(
                taskType="simulateFailure",
                payload={"failUntilAttempt": 10},  # always fails within this test's attempt budget
                maxAttempts=2,
                correlationId="corr-2",
            )
        )

    await worker.claimAndProcessOne()
    async with sessionFactory() as session:
        afterFirstAttempt = await TaskRepository(session).getTaskById(task.id)
    assert afterFirstAttempt.status == TaskStatus.QUEUED.value
    assert afterFirstAttempt.attemptCount == 1
    assert afterFirstAttempt.lastErrorCode == "RuntimeError"

    await worker.claimAndProcessOne()
    async with sessionFactory() as session:
        afterSecondAttempt = await TaskRepository(session).getTaskById(task.id)
    assert afterSecondAttempt.status == TaskStatus.DEAD_LETTER.value
    assert afterSecondAttempt.attemptCount == 2


async def testWorkerEventuallySucceedsAfterConfiguredFailures(
    engine: AsyncEngine, worker: Worker
) -> None:
    sessionFactory = createSessionFactory(engine)
    async with sessionFactory() as session:
        task = await TaskRepository(session).createTask(
            NewTaskInput(
                taskType="simulateFailure",
                payload={"failUntilAttempt": 1},
                maxAttempts=5,
                correlationId="corr-3",
            )
        )

    await worker.claimAndProcessOne()  # attempt 1: fails, requeued
    await worker.claimAndProcessOne()  # attempt 2: succeeds

    async with sessionFactory() as session:
        refreshed = await TaskRepository(session).getTaskById(task.id)
    assert refreshed.status == TaskStatus.SUCCEEDED.value
    assert refreshed.result == {"failedAttempts": 1, "succeededOnAttempt": 2}


async def testClaimAndProcessOneReturnsFalseWhenNothingIsQueued(worker: Worker) -> None:
    assert await worker.claimAndProcessOne() is False


async def testProcessFileHandlerReadsFromTheControlledDirectory(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    (tmp_path / "report.txt").write_bytes(b"line one\nline two\n")
    sessionFactory = createSessionFactory(engine)
    handlerRegistry = buildHandlerRegistry(tmp_path)
    worker = Worker(
        workerId="test-worker",
        sessionFactory=sessionFactory,
        redisClient=_NullRedis(),  # type: ignore[arg-type]
        handlerRegistry=handlerRegistry,
        leaseSeconds=30,
        pollIntervalSeconds=1.0,
    )

    async with sessionFactory() as session:
        task = await TaskRepository(session).createTask(
            NewTaskInput(
                taskType="processFile",
                payload={"fileName": "report.txt"},
                maxAttempts=1,
                correlationId="corr-4",
            )
        )

    await worker.claimAndProcessOne()

    async with sessionFactory() as session:
        refreshed = await TaskRepository(session).getTaskById(task.id)
    assert refreshed.status == TaskStatus.SUCCEEDED.value
    assert refreshed.result == {"fileName": "report.txt", "sizeBytes": 18, "lineCount": 2}
