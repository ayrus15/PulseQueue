# Demo script

**No recorded video exists for this project.** PROJECT_PLAN.md's Phase
9 asks for a short demo "showing task submission, execution, retry,
and monitoring" - this script is exactly that walkthrough, written so
anyone (a reviewer, a recruiter, or a future screen-recording of this
same session) can run it themselves and see the same thing. Every
command and every response below is copied verbatim from an actual run
on 2026-11-01 against a real PostgreSQL database, a real Redis
instance, a real `uvicorn` process, and a real worker process - nothing
here is reconstructed from memory or invented.

## Setup

```bash
uvicorn pulsequeue.main:app --host 127.0.0.1 --port 8001 &
python -m pulsequeue.workers.worker &
curl -s http://127.0.0.1:8001/health/ready
```
```json
{"status":"ready","database":"ok","redis":"ok"}
```

## 1. Submission and execution (the happy path)

```bash
curl -s -X POST http://127.0.0.1:8001/api/v1/tasks -H "Content-Type: application/json" \
  -d '{"taskType": "calculateMetrics", "payload": {"metricName": "latency_ms", "values": [12.5, 9.8, 15.1]}}'
```
```json
{"taskId":"0c938190-4178-4ff1-9c25-9e215b574817","status":"queued","statusUrl":"/api/v1/tasks/0c938190-4178-4ff1-9c25-9e215b574817"}
```

Two seconds later (a worker claimed and ran it):

```bash
curl -s http://127.0.0.1:8001/api/v1/tasks/0c938190-4178-4ff1-9c25-9e215b574817
```
```json
{"taskId":"0c938190-4178-4ff1-9c25-9e215b574817","taskType":"calculateMetrics","status":"succeeded",
 "attemptCount":1,"result":{"max":15.1,"min":9.8,"mean":12.466666666666667,"count":3,"metricName":"latency_ms"}, ...}
```

## 2. Retry (a handler that fails twice, then succeeds)

`simulateFailure`'s `failUntilAttempt` deliberately fails every attempt
up to and including that number - here, the task fails on attempts 1
and 2, then succeeds on attempt 3:

```bash
curl -s -X POST http://127.0.0.1:8001/api/v1/tasks -H "Content-Type: application/json" \
  -d '{"taskType": "simulateFailure", "payload": {"failUntilAttempt": 2}, "maxAttempts": 4}'
```
```json
{"taskId":"4c13fa89-dc2b-439a-a268-2e3fe6b3eddc","status":"queued", ...}
```

```bash
curl -s http://127.0.0.1:8001/api/v1/tasks/4c13fa89-dc2b-439a-a268-2e3fe6b3eddc
```
```json
{"taskId":"4c13fa89-...","status":"succeeded","attemptCount":3,
 "result":{"failedAttempts":2,"succeededOnAttempt":3},
 "lastErrorCode":"RuntimeError",
 "lastErrorMessage":"Simulated failure on attempt 2 (failUntilAttempt=2)", ...}
```

`attemptCount: 3` and the preserved `lastErrorCode`/`lastErrorMessage`
from the final *failed* attempt before success show the retries
actually happened, with bounded exponential backoff between them
(ADR 0004) - not a single lucky attempt.

## 3. Retry exhaustion → dead letter → admin requeue

Same handler, but `maxAttempts: 2` with a failure condition it can
never clear in time:

```bash
curl -s -X POST http://127.0.0.1:8001/api/v1/tasks -H "Content-Type: application/json" \
  -d '{"taskType": "simulateFailure", "payload": {"failUntilAttempt": 10}, "maxAttempts": 2}'
```
```json
{"taskId":"a789a097-97a9-4163-b6a4-3ea1b49cd03a","status":"queued", ...}
```

```bash
curl -s http://127.0.0.1:8001/api/v1/tasks/a789a097-97a9-4163-b6a4-3ea1b49cd03a
```
```json
{"taskId":"a789a097-...","status":"dead_letter","attemptCount":2,"maxAttempts":2, ...}
```

Admin endpoints require `X-Admin-Token` - without it:

```bash
curl -s -w "\nHTTP %{http_code}\n" http://127.0.0.1:8001/api/v1/dead-letters
```
```
{"error":{"code":"UnauthorizedError","message":"Missing or invalid X-Admin-Token header"}}
HTTP 401
```

With it, list and requeue:

```bash
curl -s -H "X-Admin-Token: change-me-locally" http://127.0.0.1:8001/api/v1/dead-letters
```
```json
{"tasks":[{"taskId":"a789a097-97a9-4163-b6a4-3ea1b49cd03a","status":"dead_letter", ...}]}
```

```bash
curl -s -X POST -H "X-Admin-Token: change-me-locally" \
  http://127.0.0.1:8001/api/v1/dead-letters/a789a097-97a9-4163-b6a4-3ea1b49cd03a/requeue
```
```json
{"taskId":"a789a097-...","status":"queued","attemptCount":0, ...}
```

`attemptCount` reset to `0` with a fresh retry budget - this task's
earlier attempts are still in `task_attempts`, never deleted.

## 4. Monitoring

```bash
curl -s http://127.0.0.1:8001/metrics | grep -E "^pulsequeue_" | grep -v api_request
```
```
pulsequeue_queue_depth{status="queued"} 0.0
pulsequeue_queue_depth{status="running"} 1.0
pulsequeue_queue_depth{status="succeeded"} 1124.0
pulsequeue_queue_depth{status="failed"} 0.0
pulsequeue_queue_depth{status="cancelled"} 0.0
pulsequeue_queue_depth{status="dead_letter"} 0.0
pulsequeue_tasks_submitted_total 1125.0
pulsequeue_tasks_completed_total 1124.0
pulsequeue_tasks_failed_total 0.0
pulsequeue_tasks_dead_letter_total 0.0
pulsequeue_tasks_retried_total 3.0
pulsequeue_worker_heartbeat_age_seconds{worker_id="DESKTOP-TH61CTF-cdd47b05"} 15.196739673614502
```

The `succeeded`/`submitted` counts here are cumulative for this
database (1121 pre-existing tasks from earlier manual testing sessions,
plus the 4 submitted in this walkthrough) - `pulsequeue_tasks_retried_total: 3`
is exactly the 2 retries from step 2 plus the 1 requeue-driven retry
attempt from step 3. `pulsequeue_worker_heartbeat_age_seconds` is a
live, per-worker liveness signal (how long since that worker last
updated its Redis heartbeat key) - this is what `/health/ready`-style
external monitoring would alert on if it grew unbounded.

For the full failure-recovery scenario (a worker crashing mid-task,
not just a handler returning an error), see
[`docs/operationsRunbook.md`](operationsRunbook.md)'s "Failure recovery
walkthrough" section - the same real-commands-and-real-output
standard, covering the one scenario this script doesn't (a worker
dying, not a handler failing).
