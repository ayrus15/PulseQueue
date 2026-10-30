"""API integration tests for dead-letter administration, including the
admin-token auth guard - against real PostgreSQL.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from pulsequeue.core.config import getSettings
from pulsequeue.main import createApp
from pulsequeue.persistence.database import createSessionFactory
from pulsequeue.persistence.repositories import NewTaskInput, TaskRepository
from pulsequeue.queueing.redisQueue import createRedisClient

ADMIN_HEADERS = {"X-Admin-Token": "change-me-locally"}  # matches Settings.adminToken's default


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    application = createApp()
    application.state.sessionFactory = createSessionFactory(engine)
    redisClient = createRedisClient(getSettings().redisUrl)
    application.state.redisClient = redisClient
    transport = ASGITransport(app=application)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as httpClient:
            yield httpClient
    finally:
        await redisClient.aclose()


async def _createDeadLetterTaskViaRepository(engine: AsyncEngine) -> str:
    sessionFactory = createSessionFactory(engine)
    async with sessionFactory() as session:
        repository = TaskRepository(session)
        task = await repository.createTask(
            NewTaskInput(
                taskType="generateReport",
                payload={"reportName": "x", "periodDays": 1},
                maxAttempts=1,
                correlationId="corr-dl",
            )
        )
        await repository.claimNextTasks(workerId="worker-1", leaseSeconds=30)
        await repository.recordFailure(
            task,
            errorCode="RuntimeError",
            errorMessage="boom",
            failedAt=datetime.now(UTC),
            isPermanent=False,
            baseDelaySeconds=1.0,
            maxDelaySeconds=60.0,
        )
        return str(task.id)


async def testListDeadLettersWithoutTokenReturns401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dead-letters")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UnauthorizedError"


async def testListDeadLettersWithWrongTokenReturns401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dead-letters", headers={"X-Admin-Token": "wrong-token"})
    assert response.status_code == 401


async def testListDeadLettersWithValidTokenReturnsTheTask(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    taskId = await _createDeadLetterTaskViaRepository(engine)

    response = await client.get("/api/v1/dead-letters", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    taskIds = [task["taskId"] for task in response.json()["tasks"]]
    assert taskId in taskIds


async def testRequeueDeadLetterReturnsItToQueued(client: AsyncClient, engine: AsyncEngine) -> None:
    taskId = await _createDeadLetterTaskViaRepository(engine)

    response = await client.post(f"/api/v1/dead-letters/{taskId}/requeue", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["attemptCount"] == 0


async def testRequeueDeadLetterWithoutTokenReturns401(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    taskId = await _createDeadLetterTaskViaRepository(engine)
    response = await client.post(f"/api/v1/dead-letters/{taskId}/requeue")
    assert response.status_code == 401


async def testRequeueingATaskThatIsNotDeadLetterReturns409(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    sessionFactory = createSessionFactory(engine)
    async with sessionFactory() as session:
        task = await TaskRepository(session).createTask(
            NewTaskInput(
                taskType="generateReport",
                payload={"reportName": "x", "periodDays": 1},
                maxAttempts=4,
                correlationId="corr-not-dl",
            )
        )

    response = await client.post(f"/api/v1/dead-letters/{task.id}/requeue", headers=ADMIN_HEADERS)
    assert response.status_code == 409
