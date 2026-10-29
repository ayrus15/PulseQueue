"""The worker process: claims eligible tasks, runs the registered
handler, and records the outcome. Runs separately from the API process:

    python -m pulsequeue.workers.worker

See docs/architecture.md for the request/claim flow and ADR 0003 for
why claiming is safe under concurrent workers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import socket
import uuid
from datetime import UTC, datetime
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulsequeue.core.config import Settings, getSettings
from pulsequeue.core.loggingConfig import configureLogging
from pulsequeue.domain.errors import PermanentTaskError
from pulsequeue.domain.models import AttemptOutcome
from pulsequeue.domain.taskTypes import validatePayload
from pulsequeue.persistence.database import createEngine, createSessionFactory
from pulsequeue.persistence.models import TaskAttemptRecord, TaskRecord
from pulsequeue.persistence.repositories import TaskAttemptRepository, TaskRepository
from pulsequeue.queueing.redisQueue import createRedisClient, waitForNotification
from pulsequeue.recovery.leaseRecovery import recoverExpiredLeases
from pulsequeue.workers.registry import HandlerFunc, buildHandlerRegistry, getHandler

logger = logging.getLogger(__name__)


class Worker:
    """Runs ``concurrency`` independent claim/process loops against the
    same database and Redis connection pool.
    """

    def __init__(
        self,
        workerId: str,
        sessionFactory: async_sessionmaker[AsyncSession],
        redisClient: Redis,
        handlerRegistry: dict[str, HandlerFunc],
        leaseSeconds: int,
        pollIntervalSeconds: float,
        retryBaseDelaySeconds: float = 1.0,
        retryMaxDelaySeconds: float = 60.0,
        concurrency: int = 1,
    ) -> None:
        self._workerId = workerId
        self._sessionFactory = sessionFactory
        self._redisClient = redisClient
        self._handlerRegistry = handlerRegistry
        self._leaseSeconds = leaseSeconds
        self._pollIntervalSeconds = pollIntervalSeconds
        self._retryBaseDelaySeconds = retryBaseDelaySeconds
        self._retryMaxDelaySeconds = retryMaxDelaySeconds
        self._concurrency = concurrency
        self._stopping = asyncio.Event()

    def requestStop(self) -> None:
        """Cooperative shutdown: each loop finishes its current claim/process
        cycle (never mid-task) before exiting. See PROJECT_PLAN.md's
        cancellation design note.
        """
        self._stopping.set()

    async def run(self) -> None:
        logger.info(
            "Worker starting",
            extra={"worker_id": self._workerId, "concurrency": self._concurrency},
        )
        try:
            await asyncio.gather(
                self._recoveryLoop(),
                *(self._loop(slot) for slot in range(self._concurrency)),
            )
        finally:
            logger.info("Worker stopped", extra={"worker_id": self._workerId})

    async def _recoveryLoop(self) -> None:
        while not self._stopping.is_set():
            await self.runOneRecoveryPass()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=self._pollIntervalSeconds)

    async def runOneRecoveryPass(self) -> list[uuid.UUID]:
        """Recover every currently-expired lease once; returns the
        recovered task IDs. Public so tests can trigger a recovery pass
        deterministically instead of running the open-ended loop.
        """
        async with self._sessionFactory() as session:
            recovered = await recoverExpiredLeases(session, datetime.now(UTC))
        if recovered:
            logger.info(
                "Lease recovery pass requeued tasks",
                extra={"worker_id": self._workerId, "recovered_count": len(recovered)},
            )
        return recovered

    async def _loop(self, slot: int) -> None:
        while not self._stopping.is_set():
            claimedSomething = await self.claimAndProcessOne()
            if not claimedSomething and not self._stopping.is_set():
                await waitForNotification(self._redisClient, self._pollIntervalSeconds)

    async def claimAndProcessOne(self) -> bool:
        """Claim and process at most one task; returns whether it found one.

        This is what ``_loop`` calls repeatedly, and it's also the public
        entry point tests use to drive the worker deterministically one
        task at a time instead of running the open-ended ``run()`` loop.
        """
        async with self._sessionFactory() as session:
            claimed = await TaskRepository(session).claimNextTasks(
                workerId=self._workerId, leaseSeconds=self._leaseSeconds, batchSize=1
            )
        if not claimed:
            return False
        await self._processTask(claimed[0].id)
        return True

    async def _processTask(self, taskId: uuid.UUID) -> None:
        async with self._sessionFactory() as session:
            taskRepository = TaskRepository(session)
            attemptRepository = TaskAttemptRepository(session)
            task = await taskRepository.getTaskById(taskId)

            startedAt = datetime.now(UTC)
            attempt = await attemptRepository.startAttempt(
                taskId=task.id,
                attemptNumber=task.attemptCount,
                workerId=self._workerId,
                startedAt=startedAt,
            )
            logContext = {
                "task_id": str(task.id),
                "worker_id": self._workerId,
                "correlation_id": task.correlationId,
                "attempt_number": task.attemptCount,
            }
            logger.info("Processing task", extra=logContext)

            try:
                payloadModel = validatePayload(task.taskType, task.payload)
                handler = getHandler(self._handlerRegistry, task.taskType)
                result = await handler(payloadModel, task.attemptCount)
            except Exception as exc:
                await self._recordFailure(
                    taskRepository, attemptRepository, task, attempt, exc, logContext
                )
            else:
                await self._recordSuccess(
                    taskRepository, attemptRepository, task, attempt, result, logContext
                )

    async def _recordSuccess(
        self,
        taskRepository: TaskRepository,
        attemptRepository: TaskAttemptRepository,
        task: TaskRecord,
        attempt: TaskAttemptRecord,
        result: dict[str, object],
        logContext: dict[str, object],
    ) -> None:
        endedAt = datetime.now(UTC)
        await taskRepository.recordSuccess(task, result=result, completedAt=endedAt)
        await attemptRepository.finishAttempt(attempt, AttemptOutcome.SUCCEEDED, endedAt=endedAt)
        logger.info("Task succeeded", extra=logContext)

    async def _recordFailure(
        self,
        taskRepository: TaskRepository,
        attemptRepository: TaskAttemptRepository,
        task: TaskRecord,
        attempt: TaskAttemptRecord,
        exc: Exception,
        logContext: dict[str, object],
    ) -> None:
        endedAt = datetime.now(UTC)
        errorCode = type(exc).__name__
        errorMessage = str(exc)
        outcome = await taskRepository.recordFailure(
            task,
            errorCode=errorCode,
            errorMessage=errorMessage,
            failedAt=endedAt,
            isPermanent=isinstance(exc, PermanentTaskError),
            baseDelaySeconds=self._retryBaseDelaySeconds,
            maxDelaySeconds=self._retryMaxDelaySeconds,
        )
        await attemptRepository.finishAttempt(
            attempt,
            outcome,
            endedAt=endedAt,
            errorCode=errorCode,
            errorMessage=errorMessage,
        )
        logger.warning(
            "Task attempt failed",
            extra={**logContext, "outcome": outcome.value, "error_code": errorCode},
        )


def buildWorkerId() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


async def runWorker(settings: Settings, workerId: str | None = None) -> None:
    resolvedWorkerId = workerId or buildWorkerId()
    engine = createEngine(settings.databaseUrl)
    sessionFactory = createSessionFactory(engine)
    redisClient = createRedisClient(settings.redisUrl)
    handlerRegistry = buildHandlerRegistry(Path(settings.processFileDirectory))

    worker = Worker(
        workerId=resolvedWorkerId,
        sessionFactory=sessionFactory,
        redisClient=redisClient,
        handlerRegistry=handlerRegistry,
        leaseSeconds=settings.workerLeaseSeconds,
        pollIntervalSeconds=settings.workerPollIntervalSeconds,
        retryBaseDelaySeconds=settings.retryBaseDelaySeconds,
        retryMaxDelaySeconds=settings.retryMaxDelaySeconds,
        concurrency=settings.workerConcurrency,
    )

    loop = asyncio.get_running_loop()
    # add_signal_handler gives truly graceful shutdown (finish the current
    # attempt, then exit) but is only implemented on Unix event loops; on
    # Windows, Ctrl+C instead raises KeyboardInterrupt through asyncio.run(),
    # which still runs this function's `finally` block but can interrupt an
    # in-flight attempt rather than waiting for it to finish.
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.requestStop)
        except NotImplementedError:
            break

    try:
        await worker.run()
    finally:
        await redisClient.aclose()
        await engine.dispose()


def main() -> None:
    settings = getSettings()
    configureLogging(settings.logLevel)
    asyncio.run(runWorker(settings))


if __name__ == "__main__":
    main()
