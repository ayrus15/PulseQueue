"""Prometheus metrics for the API process.

Task/queue metrics are computed from PostgreSQL *at scrape time*, not
accumulated as in-process Counters - an in-process Counter resets on
every API restart and diverges between multiple API instances, while a
query against the source of truth (ADR 0001) is always correct
regardless of how many times the process has restarted or how many
instances are running. API request metrics (count, duration) stay
in-process, since those are inherently per-instance.

Metric names follow Prometheus's own snake_case convention (not
PROJECT_PLAN.md's illustrative camelCase spelling) with a `pulsequeue_`
prefix, per PROJECT_PLAN.md's own instruction to "use metric naming
conventions appropriate to the selected Prometheus client."
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.domain.models import AttemptOutcome, TaskStatus
from pulsequeue.persistence.models import TaskAttemptRecord, TaskRecord
from pulsequeue.queueing.redisQueue import HEARTBEAT_KEY_PREFIX

logger = logging.getLogger(__name__)

DURATION_BUCKETS_SECONDS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
"""Shared bucket boundaries for both duration histograms below - fine
for this project's demo-handler scale; a real deployment with slower
handlers would want wider buckets."""

REGISTRY = CollectorRegistry()

apiRequestsTotal = Counter(
    "pulsequeue_api_requests_total",
    "Total API requests received",
    ["method", "path", "status_code"],
    registry=REGISTRY,
)
apiRequestDurationSeconds = Histogram(
    "pulsequeue_api_request_duration_seconds",
    "API request duration in seconds",
    ["method", "path"],
    registry=REGISTRY,
)

queueDepth = Gauge(
    "pulsequeue_queue_depth",
    "Current number of tasks in each status",
    ["status"],
    registry=REGISTRY,
)
tasksSubmittedTotal = Gauge(
    "pulsequeue_tasks_submitted_total",
    "Total tasks ever submitted (all statuses)",
    registry=REGISTRY,
)
tasksCompletedTotal = Gauge(
    "pulsequeue_tasks_completed_total",
    "Total tasks that reached succeeded",
    registry=REGISTRY,
)
tasksFailedTotal = Gauge(
    "pulsequeue_tasks_failed_total",
    "Total tasks that reached failed (permanent failure)",
    registry=REGISTRY,
)
tasksDeadLetterTotal = Gauge(
    "pulsequeue_tasks_dead_letter_total",
    "Total tasks currently dead_letter",
    registry=REGISTRY,
)
tasksRetriedTotal = Gauge(
    "pulsequeue_tasks_retried_total",
    "Total attempts that ended in a retry (across all tasks)",
    registry=REGISTRY,
)
workerHeartbeatAgeSeconds = Gauge(
    "pulsequeue_worker_heartbeat_age_seconds",
    "Seconds since each worker's last heartbeat",
    ["worker_id"],
    registry=REGISTRY,
)


async def _refreshTaskGauges(session: AsyncSession) -> None:
    statement = select(TaskRecord.status, func.count()).group_by(TaskRecord.status)
    counts = dict.fromkeys((status.value for status in TaskStatus), 0)
    for statusValue, count in (await session.execute(statement)).all():
        counts[statusValue] = count

    for statusValue, count in counts.items():
        queueDepth.labels(status=statusValue).set(count)

    tasksSubmittedTotal.set(sum(counts.values()))
    tasksCompletedTotal.set(counts[TaskStatus.SUCCEEDED.value])
    tasksFailedTotal.set(counts[TaskStatus.FAILED.value])
    tasksDeadLetterTotal.set(counts[TaskStatus.DEAD_LETTER.value])

    retriedStatement = (
        select(func.count())
        .select_from(TaskAttemptRecord)
        .where(TaskAttemptRecord.outcome == AttemptOutcome.RETRIED.value)
    )
    tasksRetriedTotal.set((await session.execute(retriedStatement)).scalar_one())


async def _refreshWorkerHeartbeatGauges(redisClient: Redis) -> None:
    try:
        keys = [key async for key in redisClient.scan_iter(match=f"{HEARTBEAT_KEY_PREFIX}*")]
        now = time.time()
        for key in keys:
            rawValue = await redisClient.get(key)
            if rawValue is None:
                continue
            workerId = key.decode("utf-8")[len(HEARTBEAT_KEY_PREFIX) :]
            lastHeartbeat = float(rawValue)
            workerHeartbeatAgeSeconds.labels(worker_id=workerId).set(now - lastHeartbeat)
    except Exception:
        # Best-effort (ADR 0002) - a /metrics scrape must never fail just
        # because Redis is unreachable; worker heartbeat gauges are simply
        # stale/missing until it's back.
        logger.warning("Failed to refresh worker heartbeat gauges from Redis", exc_info=True)


def _formatHistogram(name: str, helpText: str, samples: Sequence[float]) -> str:
    """Hand-formats a Prometheus histogram in the standard text
    exposition format, from samples fetched fresh from PostgreSQL.

    prometheus_client's own ``Histogram`` class is for in-process
    observation and doesn't fit this module's DB-is-truth model (ADR
    0001) - there's no API on it for "here are all the samples, compute
    the buckets" - so this builds the same wire format by hand instead.
    Correct cumulative ``le`` buckets, ``_sum``, and ``_count`` either way.
    """
    lines = [f"# HELP {name} {helpText}", f"# TYPE {name} histogram"]
    cumulative = 0
    sortedSamples = sorted(samples)
    sampleIndex = 0
    for boundary in DURATION_BUCKETS_SECONDS:
        while sampleIndex < len(sortedSamples) and sortedSamples[sampleIndex] <= boundary:
            sampleIndex += 1
        cumulative = sampleIndex
        lines.append(f'{name}_bucket{{le="{boundary}"}} {cumulative}')
    lines.append(f'{name}_bucket{{le="+Inf"}} {len(sortedSamples)}')
    lines.append(f"{name}_sum {sum(sortedSamples)}")
    lines.append(f"{name}_count {len(sortedSamples)}")
    return "\n".join(lines) + "\n"


async def _fetchTaskExecutionSecondsSamples(session: AsyncSession) -> list[float]:
    statement = select(TaskAttemptRecord.durationMs).where(
        TaskAttemptRecord.durationMs.is_not(None)
    )
    rows = (await session.execute(statement)).scalars().all()
    return [ms / 1000.0 for ms in rows if ms is not None]


async def _fetchTaskQueueWaitSecondsSamples(session: AsyncSession) -> list[float]:
    """Queue wait for each task's *first* claim only: ``task_attempts``
    (attempt 1) ``startedAt`` minus the task's ``createdAt``.

    Deliberately not ``TaskRecord.startedAt - TaskRecord.scheduledAt``:
    ``TaskRecord.startedAt`` is set once and preserved across retries
    (``claimNextTasks``'s ``record.startedAt or now``), but
    ``scheduledAt`` keeps moving forward on every retry/recovery - so
    for any task retried more than once, that pair compares the first
    start against the *latest* schedule time and goes negative. This
    was caught by a live smoke test, not a unit test, exactly the kind
    of thing those two timestamps' independent update rules should have
    flagged earlier.
    """
    statement = (
        select(func.extract("epoch", TaskAttemptRecord.startedAt - TaskRecord.createdAt))
        .select_from(TaskAttemptRecord)
        .join(TaskRecord, TaskAttemptRecord.taskId == TaskRecord.id)
        .where(TaskAttemptRecord.attemptNumber == 1)
    )
    rows = (await session.execute(statement)).scalars().all()
    return [float(seconds) for seconds in rows]


async def renderMetrics(session: AsyncSession, redisClient: Redis) -> bytes:
    await _refreshTaskGauges(session)
    await _refreshWorkerHeartbeatGauges(redisClient)

    executionSamples = await _fetchTaskExecutionSecondsSamples(session)
    queueWaitSamples = await _fetchTaskQueueWaitSecondsSamples(session)
    histogramsText = _formatHistogram(
        "pulsequeue_task_execution_seconds",
        "Task handler execution duration in seconds, across all recorded attempts",
        executionSamples,
    ) + _formatHistogram(
        "pulsequeue_task_queue_wait_seconds",
        "Time between task creation and its first claim, in seconds (first attempt only)",
        queueWaitSamples,
    )

    return generate_latest(REGISTRY) + histogramsText.encode("utf-8")
