# Benchmark result: 1 worker process, concurrency=1

**Status: single scenario only - the planned 1-vs-N-worker comparison
and bottleneck analysis were not completed this session (ran out of
turn budget). Do not read this as a finished Phase 7.**

## Command

```bash
# API
uvicorn pulsequeue.main:app --port 8020

# Worker
PULSEQUEUE_WORKER_CONCURRENCY=1 python -m pulsequeue.workers.worker

# Load
locust -f benchmarks/locustfile.py --host http://127.0.0.1:8020 \
  --headless -u 20 -r 5 -t 60s \
  --csv benchmarks/results/scenario1-1worker-c1
```

Database truncated (`TRUNCATE task_attempts, idempotency_records,
tasks;`) immediately before this run for a clean baseline.

## Environment

- CPU: Intel Core i5-8250U, 4 cores / 8 threads
- RAM: ~3.9 GB total (a resource-constrained VM, not production-grade)
- OS: Windows 11 Enterprise, 64-bit
- Python: 3.11.9
- PostgreSQL: 18.6 (native Windows install, not Docker)
- Redis: 8.10.3 (native Windows install, not Docker)
- No container isolation: API, worker, PostgreSQL, Redis, and Locust
  all shared this one machine's CPU/RAM during the run.

## Results (from Locust's own output, raw CSVs alongside this file)

| Metric | Value |
|---|---|
| Duration | 60s |
| Total requests | 1849 |
| Failures | 0 (0.00%) |
| Aggregate throughput | 35.04 req/s |
| POST /api/v1/tasks p50 | 420 ms |
| POST /api/v1/tasks p95 | 1300 ms |
| POST /api/v1/tasks max | 1594 ms |
| GET /api/v1/tasks/{taskId} p50 | 160 ms |

## From `/metrics`, captured immediately after the run

- `pulsequeue_tasks_submitted_total`: 842
- `pulsequeue_tasks_completed_total`: 842 (100% - **zero backlog**,
  `pulsequeue_queue_depth{status="queued"}` was 0 at the end)
- `pulsequeue_task_execution_seconds_sum` / `_count`: 3.10s / 842 →
  **~3.7 ms average handler execution time** (these are the fast,
  deterministic demo handlers - generateReport/calculateMetrics/
  sendNotification do no real I/O)
- `pulsequeue_task_queue_wait_seconds_sum` / `_count`: 250.5s / 842 →
  **~297 ms average wait** between a task's creation and its first
  claim

## What this one data point actually shows

A single worker (concurrency=1 - one claim/process loop) kept up with
~14 submissions/sec with zero backlog and zero failures. The ~297 ms
average queue wait, against a ~3.7 ms average execution time, says the
bottleneck for *this* workload at *this* load level is **not** handler
execution speed - it's almost entirely time spent waiting to be
claimed (the worker's poll/claim cycle, one task at a time with
`batchSize=1`). This is a real signal, but one scenario isn't enough
to call it "the" bottleneck - the real test (not yet run) is whether a
second worker process, or a higher `PULSEQUEUE_WORKER_CONCURRENCY`,
measurably cuts that wait time while throughput and failure rate hold.

## What's missing from this being a real Phase 7

- The 1-vs-N-worker comparison this benchmark exists to make.
- Profiling to confirm *why* claim latency is what it is (DB round-trip
  cost of `SELECT ... FOR UPDATE SKIP LOCKED` with `batchSize=1` vs.
  the poll interval itself) rather than inferring it from one number.
- A written bottleneck conclusion backed by that comparison, not just
  this single run's numbers.
