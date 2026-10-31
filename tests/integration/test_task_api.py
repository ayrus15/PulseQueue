"""API integration tests against a real PostgreSQL database.

See tests/integration/conftest.py for how the database connection is
wired and skipped when unreachable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from pulsequeue.core.config import getSettings
from pulsequeue.main import createApp
from pulsequeue.persistence.database import createSessionFactory
from pulsequeue.queueing.redisQueue import createRedisClient


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    application = createApp()
    application.state.sessionFactory = createSessionFactory(engine)
    # Redis is best-effort (ADR 0002): submission must still work when it's
    # unreachable, which this exercises whenever Redis isn't installed.
    redisClient = createRedisClient(getSettings().redisUrl)
    application.state.redisClient = redisClient
    transport = ASGITransport(app=application)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as httpClient:
            yield httpClient
    finally:
        await redisClient.aclose()


async def testSubmitThenRetrieveATask(client: AsyncClient) -> None:
    submitResponse = await client.post(
        "/api/v1/tasks",
        json={
            "taskType": "generateReport",
            "payload": {"reportName": "weekly-performance", "periodDays": 7},
        },
    )
    assert submitResponse.status_code == 201
    submitted = submitResponse.json()
    assert submitted["status"] == "queued"
    assert submitted["statusUrl"] == f"/api/v1/tasks/{submitted['taskId']}"

    getResponse = await client.get(submitted["statusUrl"])
    assert getResponse.status_code == 200
    detail = getResponse.json()
    assert detail["taskId"] == submitted["taskId"]
    assert detail["taskType"] == "generateReport"
    assert detail["status"] == "queued"
    assert detail["attemptCount"] == 0
    assert detail["maxAttempts"] == 4  # PULSEQUEUE_DEFAULT_MAX_ATTEMPTS default
    assert detail["result"] is None
    assert detail["lastErrorCode"] is None


async def testSubmitRespectsExplicitMaxAttempts(client: AsyncClient) -> None:
    submitResponse = await client.post(
        "/api/v1/tasks",
        json={
            "taskType": "sendNotification",
            "payload": {"recipientName": "Arjun Ramesh", "message": "hello"},
            "maxAttempts": 2,
        },
    )
    assert submitResponse.status_code == 201
    taskId = submitResponse.json()["taskId"]

    detail = (await client.get(f"/api/v1/tasks/{taskId}")).json()
    assert detail["maxAttempts"] == 2


async def testSubmitRejectsUnsupportedTaskType(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/tasks", json={"taskType": "deleteEverything", "payload": {}}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UnsupportedTaskTypeError"


async def testSubmitRejectsInvalidPayloadForTaskType(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/tasks",
        json={"taskType": "generateReport", "payload": {"reportName": "x", "periodDays": 9999}},
    )
    assert response.status_code == 422


async def testSubmitRejectsMalformedRequestBody(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tasks", json={"payload": {}})
    assert response.status_code == 422


async def testSubmitRejectsAPathTraversalFileName(client: AsyncClient) -> None:
    """A processFile submission with an unsafe fileName is rejected at
    submission (422) rather than accepted and only failing later in the
    worker - see ProcessFilePayload's field_validator (Phase 8 hardening).
    """
    response = await client.post(
        "/api/v1/tasks",
        json={"taskType": "processFile", "payload": {"fileName": "../../etc/passwd"}},
    )
    assert response.status_code == 422


async def testGetUnknownTaskReturns404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TaskNotFoundError"


async def testGetTaskWithMalformedIdReturns422(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/not-a-uuid")
    assert response.status_code == 422


async def testRepeatingAnIdempotencyKeyReturnsTheOriginalTaskWith200(client: AsyncClient) -> None:
    payload = {
        "taskType": "generateReport",
        "payload": {"reportName": "weekly", "periodDays": 7},
    }
    headers = {"Idempotency-Key": "api-key-1"}

    first = await client.post("/api/v1/tasks", json=payload, headers=headers)
    assert first.status_code == 201
    firstTaskId = first.json()["taskId"]

    second = await client.post("/api/v1/tasks", json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json()["taskId"] == firstTaskId


async def testReusingAnIdempotencyKeyWithADifferentPayloadReturns409(
    client: AsyncClient,
) -> None:
    headers = {"Idempotency-Key": "api-key-2"}
    first = await client.post(
        "/api/v1/tasks",
        json={"taskType": "generateReport", "payload": {"reportName": "a", "periodDays": 1}},
        headers=headers,
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/tasks",
        json={"taskType": "generateReport", "payload": {"reportName": "b", "periodDays": 1}},
        headers=headers,
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IdempotencyConflictError"


async def testListTasksReturnsSubmittedTasks(client: AsyncClient) -> None:
    submitted = await client.post(
        "/api/v1/tasks",
        json={"taskType": "generateReport", "payload": {"reportName": "list-me", "periodDays": 1}},
    )
    taskId = submitted.json()["taskId"]

    response = await client.get("/api/v1/tasks")
    assert response.status_code == 200
    body = response.json()
    assert taskId in {task["taskId"] for task in body["tasks"]}
    assert "nextCursor" in body


async def testListTasksRespectsLimitAndReturnsANextCursor(client: AsyncClient) -> None:
    for i in range(3):
        await client.post(
            "/api/v1/tasks",
            json={"taskType": "generateReport", "payload": {"reportName": str(i), "periodDays": 1}},
        )

    response = await client.get("/api/v1/tasks", params={"limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert len(body["tasks"]) == 2
    assert body["nextCursor"] is not None

    nextResponse = await client.get(
        "/api/v1/tasks", params={"limit": 2, "cursor": body["nextCursor"]}
    )
    assert nextResponse.status_code == 200
    firstPageIds = {task["taskId"] for task in body["tasks"]}
    secondPageIds = {task["taskId"] for task in nextResponse.json()["tasks"]}
    assert firstPageIds.isdisjoint(secondPageIds)


async def testListTasksFiltersByTaskType(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/tasks",
        json={"taskType": "sendNotification", "payload": {"recipientName": "x", "message": "hi"}},
    )

    response = await client.get("/api/v1/tasks", params={"taskType": "sendNotification"})
    assert response.status_code == 200
    assert all(task["taskType"] == "sendNotification" for task in response.json()["tasks"])


async def testListTasksRejectsAnUnknownStatusFilter(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks", params={"status": "not-a-real-status"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ValidationError"


async def testListTasksRejectsAMalformedCursor(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks", params={"cursor": "not-a-valid-cursor!!!"})
    assert response.status_code == 422


async def testCancelQueuedTaskSucceeds(client: AsyncClient) -> None:
    submitted = await client.post(
        "/api/v1/tasks",
        json={
            "taskType": "generateReport",
            "payload": {"reportName": "cancel-me", "periodDays": 1},
        },
    )
    taskId = submitted.json()["taskId"]

    response = await client.post(f"/api/v1/tasks/{taskId}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


async def testCancelUnknownTaskReturns404(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tasks/00000000-0000-0000-0000-000000000000/cancel")
    assert response.status_code == 404


async def testResponseEchoesAGeneratedCorrelationIdWhenNoneIsSent(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks")
    assert response.status_code == 200
    assert response.headers["X-Correlation-Id"]  # present and non-empty


async def testResponseEchoesTheClientsOwnCorrelationId(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks", headers={"X-Correlation-Id": "my-trace-id-123"})
    assert response.headers["X-Correlation-Id"] == "my-trace-id-123"


async def testSubmittedTaskGetsTheRequestsCorrelationId(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/tasks",
        json={"taskType": "generateReport", "payload": {"reportName": "x", "periodDays": 1}},
        headers={"X-Correlation-Id": "trace-abc"},
    )
    taskId = response.json()["taskId"]

    detail = await client.get(f"/api/v1/tasks/{taskId}")
    assert detail.json()["correlationId"] == "trace-abc"


async def testAnInvalidCorrelationIdHeaderIsReplacedWithAGeneratedOne(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/tasks", headers={"X-Correlation-Id": "has spaces/and$symbols!"}
    )
    assert response.headers["X-Correlation-Id"] != "has spaces/and$symbols!"
    assert response.headers["X-Correlation-Id"]


@pytest_asyncio.fixture
async def clientWithUnreachableRedis(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """Fault injection: Redis is unreachable *after* the task would
    already be durably committed to PostgreSQL - ADR 0002's actual
    claim, exercised here against a real (if deliberately unreachable)
    Redis client rather than a mock.
    """
    application = createApp()
    application.state.sessionFactory = createSessionFactory(engine)
    redisClient = createRedisClient("redis://localhost:1/0")  # port 1: nothing listens there
    application.state.redisClient = redisClient
    transport = ASGITransport(app=application)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as httpClient:
            yield httpClient
    finally:
        await redisClient.aclose()


async def testSubmissionSucceedsWhenRedisIsUnreachableAfterCommit(
    clientWithUnreachableRedis: AsyncClient,
) -> None:
    response = await clientWithUnreachableRedis.post(
        "/api/v1/tasks",
        json={"taskType": "generateReport", "payload": {"reportName": "x", "periodDays": 1}},
    )
    assert response.status_code == 201
    taskId = response.json()["taskId"]

    # The task is durably there regardless of whether Redis ever saw it.
    detail = await clientWithUnreachableRedis.get(f"/api/v1/tasks/{taskId}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "queued"
