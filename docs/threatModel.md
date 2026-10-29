# Threat model

**Status: updated through Phase 3; will be more thoroughly verified in
Phase 8 (security hardening).** This is not a professional security
audit.

## Assets

- Task payloads and results (may contain user-supplied data).
- Administrative operations: dead-letter listing and requeue.
- The PostgreSQL and Redis connections and their credentials.

## Trust boundaries

- The public API is the only externally reachable surface. Workers and
  the recovery loop never accept inbound connections.
- Administrative endpoints (`GET /api/v1/dead-letters`,
  `POST /api/v1/dead-letters/{taskId}/requeue`) require a shared admin
  token (`X-Admin-Token`, checked with `secrets.compare_digest` against
  `PULSEQUEUE_ADMIN_TOKEN` - see `api/dependencies.py::requireAdminToken`)
  until real per-client authentication/authorization is implemented;
  they must never be exposed without it. Verified by tests: no token or
  the wrong token → `401`, never a silent pass. This is a documented
  interim control, not a substitute for per-user authentication - in
  particular, every holder of the one shared token can requeue or
  inspect every task, with no per-client audit trail.
- Task handlers run inside the worker process with no network or
  filesystem access beyond what each handler explicitly needs:
  `processFile` is restricted to a single configured directory, with
  path-traversal checks, and no handler executes `eval`, arbitrary
  Python, or an unrestricted shell command. Task types are restricted to
  an explicit registry; an unregistered type is rejected at submission,
  not at execution time.

## Known limitations (by design — see the ADRs)

- **No exactly-once execution.** A worker can complete a side effect and
  crash before recording success, causing the task to run again after
  recovery (ADR 0003, ADR 0004). Handlers are expected to be idempotent
  where this matters; PulseQueue cannot enforce that for arbitrary
  handlers.
- **Redis is not a durability boundary.** Losing Redis cannot lose a
  task, but it can delay discovery of new work up to the poll interval
  (ADR 0002).
- **No multi-tenant isolation yet.** Idempotency keys are scoped by a
  constant `"default"` scope (not per-client) until real authentication
  exists - the schema already supports per-client scoping without a
  migration (ADR 0004), but today, any two clients could collide on the
  same idempotency key.

## To be completed in Phase 8

- Dependency vulnerability review.
- Confirmation that error responses never leak stack traces or internal
  identifiers.
- Confirmation that logs never contain full task payloads where they
  could carry sensitive data, only sanitized summaries.
- Review of rate limiting / request size limits for the public API.
