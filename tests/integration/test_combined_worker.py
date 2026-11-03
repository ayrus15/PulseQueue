"""Integration test for PULSEQUEUE_RUN_WORKER_IN_PROCESS - main.py's
lifespan starting the worker as a background task inside the API
process. Added for free-tier hosts with no separate place to run a
background process (Render's free tier, specifically - see
docs/deployment.md); not the documented two-process architecture, so
this only has to prove the deployment-cost concession actually works,
not duplicate the real worker's own test coverage.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from pulsequeue.core.config import Settings
from pulsequeue.main import createApp, lifespan
from pulsequeue.persistence.database import createSessionFactory
from pulsequeue.persistence.repositories import NewTaskInput, TaskRepository
from tests.integration.conftest import testDatabaseUrl as getTestDatabaseUrl


async def testInProcessWorkerProcessesATaskThenShutsDownCleanly(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        DATABASE_URL=getTestDatabaseUrl(),
        PULSEQUEUE_RUN_WORKER_IN_PROCESS=True,
        PULSEQUEUE_WORKER_POLL_INTERVAL_SECONDS=0.1,
    )
    monkeypatch.setattr("pulsequeue.main.getSettings", lambda: settings)

    sessionFactory = createSessionFactory(engine)
    async with sessionFactory() as session:
        task = await TaskRepository(session).createTask(
            NewTaskInput(
                taskType="calculateMetrics",
                payload={"metricName": "x", "values": [1.0, 2.0]},
                maxAttempts=4,
                correlationId="test-in-process-worker",
            )
        )
        taskId = task.id

    application = createApp()
    refreshed = None
    # Entering/exiting this block is itself part of what's being tested:
    # it would hang or raise on exit if requestStop()/await workerTask
    # in main.py's lifespan didn't shut the in-process worker down cleanly.
    async with lifespan(application):
        for _ in range(50):  # up to 5s for the worker to notice and finish
            await asyncio.sleep(0.1)
            async with sessionFactory() as session:
                refreshed = await TaskRepository(session).getTaskById(taskId)
            # "running" is a real but non-terminal state the task passes
            # through - stop polling only once it reaches a terminal one,
            # not on the first status change (a fast CI runner can easily
            # catch it mid-"running" on the very first poll).
            if refreshed.status not in ("queued", "running"):
                break

    assert refreshed is not None
    assert refreshed.status == "succeeded"
