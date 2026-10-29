# ADR 0004: Retry and idempotency semantics

**Status:** Accepted

## Context

Clients may retry HTTP submissions (network timeouts, their own retry
logic). Tasks themselves may fail for transient or permanent reasons and
need a bounded, predictable retry policy, with a place for tasks to land
once they exhaust retries.

## Decision

### Request-level idempotency (client → API)

- Clients may send an `Idempotency-Key` header on `POST /api/v1/tasks`.
- The server computes a fingerprint of the logical request (task type +
  normalized payload + max attempts) and stores
  `(scope, idempotencyKey) -> (fingerprint, originalTaskId)` in
  `idempotency_records`, with a **unique constraint** on
  `(scope, idempotency_key)` enforced by PostgreSQL — not only checked
  in application code, so two concurrent requests with the same key
  cannot both insert a new task.
- Same key + same fingerprint → return the original task
  (`200 OK`, not `201 Created`).
- Same key + different fingerprint → `409 Conflict`.
- `scope` defaults to a constant until authentication exists (see
  `docs/threatModel.md`); it is designed so per-client scoping can be
  added later without a schema change.

### Task-level retry policy (worker → handler)

- Each task has `attemptCount` and `maxAttempts` (default from
  `PULSEQUEUE_DEFAULT_MAX_ATTEMPTS`, overridable per submission).
- Delay before attempt *n* (n ≥ 2):
  `delay = min(maxDelay, baseDelay * 2 ** (n - 2)) + jitter`,
  where `jitter` is a random value in `[0, delay * 0.2]`. The delay
  calculator takes `attemptNumber`, `baseDelay`, and `maxDelay` as plain
  arguments (no sleeping, no wall-clock dependency) so it is unit
  testable without waiting.
- Errors are classified at the point they are raised:
  - **Permanent** (`ValidationError`, unsupported task type) → never
    retried; task goes straight to `failed`.
  - **Retryable** (declared handler exception, transient I/O) → retried
    up to `maxAttempts`, then moved to `dead_letter`.
  - Anything unexpected (a bug in a handler) is treated as retryable but
    logged at `ERROR` so it is visible, rather than silently swallowed.
- `dead_letter` tasks keep their full attempt history. An administrator
  can `POST /api/v1/dead-letters/{taskId}/requeue`, which resets
  `status` to `queued` and `attemptCount` to 0 while preserving the old
  attempt rows for audit.

## Consequences

- PostgreSQL's unique constraint is the actual duplicate-prevention
  mechanism; a concurrency test submits the same key simultaneously from
  multiple clients to prove only one task is created.
- Retry timing is deterministic and testable via pure functions; no
  test needs to sleep through real backoff delays.
- **We do not claim exactly-once task execution.** A handler's side
  effect can repeat if a worker crashes between doing the work and
  recording success (see ADR 0003). Demo handlers are written to be
  idempotent (e.g. `generateReport` overwrites the same report key
  rather than appending) so this limitation is demonstrable rather than
  hidden.
