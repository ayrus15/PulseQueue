# Operations runbook

**Status: written against the actual Phase 1-6 implementation**, run
directly (no Docker Compose stack yet - Phase 9). Every command below
has been run for real on this machine; nothing here is speculative.

## Starting the stack

```bash
# API
uvicorn pulsequeue.main:app --host 0.0.0.0 --port 8000

# Worker (run as many as you want; each gets its own generated worker ID)
python -m pulsequeue.workers.worker
```

Both read configuration from the environment (`.env` if present - see
`.env.example`). At minimum, `DATABASE_URL` must point at a reachable
PostgreSQL with migrations applied (`alembic upgrade head`); `REDIS_URL`
is optional (ADR 0002 - everything still works without it, just with
higher latency between submission and claim).

## Stopping the stack

Ctrl+C (SIGINT) or SIGTERM. The worker's shutdown is cooperative - it
finishes whatever claim/process cycle is in flight, then exits - except
on Windows, where `asyncio`'s event loop doesn't support
`add_signal_handler`, so Ctrl+C there raises `KeyboardInterrupt`
immediately rather than waiting (see `workers/worker.py::runWorker`'s
comment). On Linux/Docker this is a non-issue.

## Reading health checks

```bash
curl http://localhost:8000/health/live    # {"status": "alive"} - process is up
curl http://localhost:8000/health/ready   # checks PostgreSQL + Redis
```

`/health/ready` returns `503` only if **PostgreSQL** is unreachable -
that's the real correctness dependency (ADR 0001). Redis being
unreachable is reported in the body (`"redis": "unreachable"`) but
never fails readiness, since the system is designed to keep working
without it (ADR 0002). If `/health/ready` reports `"database":
"unreachable"`: check the API process's `DATABASE_URL`, and that
PostgreSQL itself is up (`pg_isready` or `psql -c "SELECT 1"`).

## Reading `/metrics`

```bash
curl http://localhost:8000/metrics
```

Everything task/queue-related is computed fresh from PostgreSQL on
every scrape (not accumulated in the API process), so it's correct
immediately after a restart and consistent across multiple API
instances. Key things to look at:

- **`pulsequeue_queue_depth{status="queued"}`** growing without
  bound → tasks are arriving faster than workers can claim/finish them.
  Check `pulsequeue_worker_heartbeat_age_seconds` (below) for whether
  workers are actually alive, and consider starting more worker
  processes (each one adds `PULSEQUEUE_WORKER_CONCURRENCY` claim loops).
- **`pulsequeue_queue_depth{status="dead_letter"}`** growing → tasks
  are exhausting their retries. See "Inspecting and requeuing dead
  letters" below before assuming it's safe to just requeue them.
- **`pulsequeue_worker_heartbeat_age_seconds{worker_id="..."}`** - each
  running worker refreshes its own key in Redis every
  `PULSEQUEUE_WORKER_POLL_INTERVAL_SECONDS`. A worker whose gauge is
  missing entirely (not just high) has either stopped or lost Redis for
  longer than the heartbeat TTL (30s) - check that worker process's own
  logs; it may still be processing tasks correctly via its DB poll even
  with Redis down (ADR 0002), so a missing heartbeat gauge alone is not
  proof the worker is dead.
- **`pulsequeue_task_execution_seconds`** / **`pulsequeue_task_queue_wait_seconds`** -
  real histograms built from `task_attempts`/`tasks` data, not
  estimates. A rising `task_queue_wait_seconds` with stable
  `task_execution_seconds` points at not enough worker capacity, not
  slow handlers.
- **`pulsequeue_api_request_duration_seconds`** - labeled by route
  template (e.g. `/api/v1/tasks/{taskId}`), never by raw path, so it
  stays low-cardinality even with many distinct task IDs.

## Reading structured logs

Every log line is JSON (`core/loggingConfig.py`). Worker lines include
`task_id`, `worker_id`, `correlation_id`, and `attempt_number`; API
request lines include `method`, `path`, `status_code`, `duration_ms`,
and `correlation_id`. To trace one request end to end: take the
`X-Correlation-Id` response header value (or the one you sent), and
`grep` every log stream for it - it threads from the HTTP request
through to the task row it created and every worker log line about
that task's attempts (`routes/tasks.py` uses the request's correlation
ID as the new task's `correlationId`).

## Diagnosing a growing queue

1. Check `pulsequeue_queue_depth{status="queued"}` is actually rising
   over time (a snapshot alone doesn't tell you direction - scrape
   twice a minute or so apart).
2. Check `pulsequeue_worker_heartbeat_age_seconds` for every worker you
   expect to be running. None present or all stale → no workers are
   actually polling; start one.
3. If workers are alive and heartbeating but the queue still grows,
   compare `pulsequeue_tasks_submitted_total`'s rate of change against
   completed+failed+dead_letter's combined rate of change - if
   submission is simply faster than total throughput, that's a
   capacity problem: start more worker processes or raise
   `PULSEQUEUE_WORKER_CONCURRENCY`.
4. If throughput looks fine but depth still grows, check
   `pulsequeue_task_execution_seconds` for a handler that's gotten slow
   (a real regression) vs. `pulsequeue_task_queue_wait_seconds` growing
   on its own (a capacity problem, not a handler problem).

## Inspecting and requeuing dead letters

```bash
curl http://localhost:8000/api/v1/dead-letters -H "X-Admin-Token: $PULSEQUEUE_ADMIN_TOKEN"
```

Read `lastErrorCode`/`lastErrorMessage` on each task before requeuing
anything - a dead-lettered task that failed because of a bug in the
handler, or because of invalid input baked into its payload, will fail
the exact same way again if you just requeue it. Requeuing resets
`attemptCount` to 0 but does **not** delete the existing `task_attempts`
rows, so the task's full failure history before this point is still
there if you need it.

```bash
curl -X POST http://localhost:8000/api/v1/dead-letters/<taskId>/requeue \
  -H "X-Admin-Token: $PULSEQUEUE_ADMIN_TOKEN"
```

Requeuing a task that isn't actually `dead_letter` returns `409` -
intentional, not a bug: it protects against accidentally resetting a
task that's `running` or already `succeeded`.

## Recovering from each documented fault scenario

See [`docs/threatModel.md`](threatModel.md) for the full list of known
limitations and [`PROJECT_PLAN.md`](../PROJECT_PLAN.md) section 11 for
the fault scenarios this project was built to survive. In short:

| Scenario | What actually happens | Verified by |
|---|---|---|
| Worker killed mid-attempt | Lease expires; recovery loop (every worker's own poll interval) returns the task to `queued` and closes the orphaned attempt as `lease_expired` | `tests/integration/test_lease_recovery.py` |
| Redis unreachable (before or after a task is committed) | Submission and worker claiming both still work, just with higher latency (poll interval, not instant wake-up); logged as warnings, not errors | `tests/integration/test_task_api.py::testSubmissionSucceedsWhenRedisIsUnreachableAfterCommit`, manual testing with Redis genuinely stopped |
| Concurrent duplicate submissions (same `Idempotency-Key`) | Exactly one task is created; the rest get the original task back (200) or a 409 if the payload differs | `tests/integration/test_idempotency.py::testConcurrentDuplicateSubmissionsCreateExactlyOneTask` |
| Cancel racing a worker's claim | Exactly one side wins the row; the task never ends up silently corrupted into `cancelled` after it started running | `tests/integration/test_task_listing.py::testCancelRacingWithClaimNeverCancelsAClaimedTask` |
| Retry exhaustion | Task moves to `dead_letter`, inspectable and requeueable via the admin endpoints above | `tests/integration/test_worker.py` |
| Permanent (non-retryable) handler error | Task moves straight to `failed`, even with retry attempts still available | `tests/integration/test_worker.py::testPermanentFailureGoesStraightToFailedNotDeadLetter` |

**Not yet handled by an automated test**: a PostgreSQL connection
failure mid-request. The API will return `500` (never a raw stack
trace - `api/errorHandlers.py`'s catch-all) and `/health/ready` will
report `503` once PostgreSQL is reachable again for that check to run;
no automatic retry of a failed request exists at the API layer today.
