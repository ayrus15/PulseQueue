"""Integration tests for GET /metrics against real PostgreSQL and Redis."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from pulsequeue.core.config import getSettings
from pulsequeue.main import createApp
from pulsequeue.observability.health import checkRedis
from pulsequeue.observability.metrics import _fetchTaskQueueWaitSecondsSamples
from pulsequeue.persistence.database import createSessionFactory
from pulsequeue.persistence.repositories import NewTaskInput, TaskRepository
from pulsequeue.queueing.redisQueue import createRedisClient, recordHeartbeat


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


async def testMetricsReturns200WithPrometheusContentType(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


async def testMetricsReflectsRealQueueDepth(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/tasks",
        json={"taskType": "generateReport", "payload": {"reportName": "x", "periodDays": 1}},
    )

    response = await client.get("/metrics")
    body = response.text

    assert 'pulsequeue_queue_depth{status="queued"}' in body
    assert "pulsequeue_tasks_submitted_total" in body


async def testMetricsIncludesApiRequestCounters(client: AsyncClient) -> None:
    await client.get("/api/v1/tasks")  # generate at least one prior request

    response = await client.get("/metrics")
    body = response.text

    assert "pulsequeue_api_requests_total" in body
    assert "pulsequeue_api_request_duration_seconds" in body


async def testMetricsIncludesDurationHistograms(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    body = response.text

    assert "pulsequeue_task_execution_seconds_count" in body
    assert "pulsequeue_task_queue_wait_seconds_count" in body


async def testMetricsReflectsAFreshWorkerHeartbeat(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    redisClient = createRedisClient(getSettings().redisUrl)
    try:
        if not await checkRedis(redisClient):
            pytest.skip("Redis unreachable - heartbeat gauge cannot be exercised")
        await recordHeartbeat(redisClient, "test-worker-123", time.time())
    finally:
        await redisClient.aclose()

    response = await client.get("/metrics")
    body = response.text

    assert 'pulsequeue_worker_heartbeat_age_seconds{worker_id="test-worker-123"}' in body


async def testQueueWaitSamplesStayNonNegativeForARetriedTask(dbSession: AsyncSession) -> None:
    """Regression test: a live smoke test caught
    ``TaskRecord.startedAt - TaskRecord.scheduledAt`` going negative for
    any task retried more than once, because ``startedAt`` is set once
    (and kept across retries) while ``scheduledAt`` keeps moving forward
    on each retry. Reproduces that exact shape - claim, fail, claim
    again - and asserts the fixed computation (first-attempt ``startedAt``
    minus the task's ``createdAt``) stays sane.
    """
    repository = TaskRepository(dbSession)
    task = await repository.createTask(
        NewTaskInput(
            taskType="generateReport",
            payload={"reportName": "x", "periodDays": 1},
            maxAttempts=3,
            correlationId="corr-metrics-regression",
        )
    )

    await asyncio.sleep(0.05)
    await repository.claimNextTasks(workerId="worker-1", leaseSeconds=30)
    await repository.recordFailure(
        task,
        errorCode="RuntimeError",
        errorMessage="boom",
        failedAt=datetime.now(UTC),
        isPermanent=False,
        baseDelaySeconds=0.01,
        maxDelaySeconds=0.02,
    )
    await asyncio.sleep(0.05)
    # scheduledAt is now well after the task's original startedAt.
    await repository.claimNextTasks(workerId="worker-1", leaseSeconds=30)

    samples = await _fetchTaskQueueWaitSecondsSamples(dbSession)

    assert all(sample >= 0 for sample in samples)
