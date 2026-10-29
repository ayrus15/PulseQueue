# ADR 0001: PostgreSQL is the source of truth for task state

**Status:** Accepted

## Context

PulseQueue accepts tasks over HTTP, queues them, and executes them on
separate worker processes. We need one component that can always answer
"does this task exist, and what state is it in?" — including after a
worker crashes, after Redis restarts, or after the whole stack is
redeployed.

## Decision

PostgreSQL holds the authoritative record of every task: its payload,
status, attempt history, lease ownership, and timestamps. A task is
considered accepted only once its row (and any idempotency record) has
committed to PostgreSQL. Redis is never the only place a task's
existence or state is recorded.

## Consequences

- Every state transition is a PostgreSQL write, enforced by the
  application's state machine (see [`docs/architecture.md`](../architecture.md)).
- Redis outages or restarts can degrade *latency* (how quickly a worker
  learns about new work) but cannot cause data loss. See
  [ADR 0002](0002-redis-role-and-recovery.md).
- All consistency and recovery guarantees are checked against
  PostgreSQL, not Redis.
- This adds one extra round trip per submission compared to queuing
  directly in Redis, which we accept in exchange for durability and a
  queryable audit trail.
