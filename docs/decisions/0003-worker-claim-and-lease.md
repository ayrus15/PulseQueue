# ADR 0003: Worker claim and lease design

**Status:** Accepted

## Context

Multiple worker processes (and multiple concurrent workers within a
process) poll PostgreSQL for eligible tasks. Two workers must never both
believe they own the same task. A worker can also crash or be killed
mid-task, and that task must eventually become eligible for another
worker without being picked up twice while the original worker might
still be running.

## Decision

- Each worker has a stable `workerId` (process/host identifier + a
  random suffix).
- Claiming a task is a single PostgreSQL transaction:
  `SELECT id FROM tasks WHERE status = 'queued' AND scheduled_at <= now()
  ORDER BY scheduled_at, created_at LIMIT :batch FOR UPDATE SKIP LOCKED`,
  followed by an `UPDATE` that sets `status = 'running'`,
  `lease_owner = :workerId`, `lease_expires_at = now() + :leaseSeconds`,
  `started_at = now()` (on first attempt) in the same transaction.
  `SKIP LOCKED` means a second worker's concurrent claim simply skips
  rows already locked by the first, so no two workers can claim the same
  row.
- While executing, a worker periodically **renews** its lease
  (`lease_expires_at = now() + :leaseSeconds`) with an `UPDATE ... WHERE
  id = :taskId AND lease_owner = :workerId`. The `WHERE lease_owner =
  :workerId` guard means a worker whose lease already expired and was
  reclaimed by someone else fails to renew (0 rows updated) and must
  stop working on the task.
- Every write a worker makes to a task's terminal state (`succeeded`,
  `failed`, `queued` for retry, `dead_letter`) is guarded the same way:
  `UPDATE tasks SET ... WHERE id = :taskId AND lease_owner = :workerId`.
  A stale worker's write therefore affects zero rows instead of
  overwriting a newer worker's result.
- A separate, simple recovery check (run from the same poll loop) finds
  rows where `status = 'running' AND lease_expires_at < now()` and
  resets them to `queued` (incrementing nothing — the original worker's
  attempt record is closed out as `lease_expired`), making them eligible
  for a new claim.

## Consequences

- No distributed lock service is needed; PostgreSQL row locking and
  conditional updates are sufficient at this scale.
- **This does not provide exactly-once execution.** A worker can
  complete a side effect (e.g. call an external API) and crash before
  its `UPDATE ... SET status = 'succeeded'` commits. The lease will
  expire, the task will be requeued, and the side effect may run again.
  This is documented in [`docs/threatModel.md`](../threatModel.md) and
  in the API docs; handlers are expected to be idempotent where that
  matters (see ADR 0004).
- Lease duration is a trade-off: too short reclaims live tasks from
  slow-but-healthy workers; too long delays recovery from a real crash.
  Default is configurable (`PULSEQUEUE_WORKER_LEASE_SECONDS`).
