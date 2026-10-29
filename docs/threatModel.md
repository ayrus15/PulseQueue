# Threat model

**Status: initial draft (Phase 0). Will be expanded and verified against
real code in Phase 8 (security hardening).** This is not a professional
security audit.

## Assets

- Task payloads and results (may contain user-supplied data).
- Administrative operations: dead-letter listing and requeue.
- The PostgreSQL and Redis connections and their credentials.

## Trust boundaries (planned)

- The public API is the only externally reachable surface. Workers and
  the recovery loop never accept inbound connections.
- Administrative endpoints (`/api/v1/dead-letters*`) require a shared
  admin token (`X-Admin-Token`, see `.env.example`) until real
  authentication/authorization is implemented; they must never be
  exposed without it. This is a documented interim control, not a
  substitute for per-user authentication.
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
- **No multi-tenant isolation yet.** Idempotency scope and
  authentication are designed to be added later (ADR 0004) but are not
  implemented in Phase 0/1.

## To be completed in Phase 8

- Dependency vulnerability review.
- Confirmation that error responses never leak stack traces or internal
  identifiers.
- Confirmation that logs never contain full task payloads where they
  could carry sensitive data, only sanitized summaries.
- Review of rate limiting / request size limits for the public API.
