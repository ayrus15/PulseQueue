# ADR 0002: Redis role is a latency optimization, not a delivery mechanism

**Status:** Accepted

## Context

A task is committed to PostgreSQL by the API process. Workers run in a
separate process and need to find eligible `queued` tasks. There are two
common designs:

1. **Transactional outbox**: insert the task and an outbox event in one
   transaction; a dispatcher reads the outbox and publishes to Redis;
   events are marked published only after a successful publish.
2. **Database polling (pull model)**: workers periodically query
   PostgreSQL directly for eligible tasks (`status = 'queued' AND
   scheduled_at <= now()`), claiming rows with `SELECT ... FOR UPDATE
   SKIP LOCKED`. Redis is used only to *wake up* idle workers sooner,
   as a best-effort notification.

Writing to PostgreSQL and publishing to Redis is never one atomic
operation. Any design that treats them as atomic can lose tasks (DB
commit succeeds, Redis publish fails or is never delivered) or double
deliver them.

## Decision

Use **database polling with Redis as a latency optimization only**
(option 2), not a transactional outbox.

- After committing a task, the API publishes a lightweight "a task may
  be ready" notification on a Redis Pub/Sub channel (or pushes a token
  to a list). Workers that are idle and subscribed wake up immediately
  and poll PostgreSQL.
- Independently of any notification, every worker also polls PostgreSQL
  on a fixed interval (`PULSEQUEUE_WORKER_POLL_INTERVAL_SECONDS`,
  default 1s). This poll is the correctness guarantee; the Redis
  notification is purely a latency improvement.
- If Redis is down, unreachable, or drops a notification, workers keep
  finding and executing tasks — just with latency bounded by the poll
  interval instead of near-instant wake-up.
- The same poll loop recovers tasks whose worker lease expired (see
  [ADR 0003](0003-worker-claim-and-lease.md)), so there is a single
  code path for "new work" and "abandoned work."

## Why not a transactional outbox

An outbox is the more scalable design at high throughput (no polling
load on the primary table) but adds a second table, a dispatcher
process, and its own at-least-once/idempotent-publish logic — complexity
that is not justified at this project's scale and that would duplicate
the recovery logic we need anyway for lease expiry. Polling with
`SKIP LOCKED` is simpler, is still correct and recoverable, and makes
the "Redis is explicitly best-effort" guarantee easy to demonstrate in
a fault-injection test (kill Redis, show tasks still complete, just
slower). We may revisit this if benchmarking in Phase 7 shows polling
load is a real bottleneck.

## Consequences

- No outbox table or separate dispatcher process.
- Redis unavailability is a documented, tested degradation path, not a
  failure mode that loses tasks.
- Poll interval is a tunable latency/load trade-off, documented in
  `.env.example`.
