# Threat model

**Status: updated through Phase 8 (security hardening).** This is not
a professional security audit.

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
- Every connection the app makes (DB, Redis) and every request it
  serves has an explicit timeout - `PULSEQUEUE_DB_*`,
  `PULSEQUEUE_REDIS_CONNECT_TIMEOUT_SECONDS`,
  `PULSEQUEUE_TASK_EXECUTION_TIMEOUT_SECONDS`,
  `PULSEQUEUE_API_REQUEST_TIMEOUT_SECONDS` (see `.env.example`). Without
  these, a hung TCP handshake, a stuck query, or a hung handler could
  previously occupy a connection/worker slot/request indefinitely.
- A request whose declared `Content-Length` exceeds
  `PULSEQUEUE_MAX_REQUEST_BODY_BYTES` (default 1 MB) is rejected with
  413 before the body is read, so a client can't make the server buffer
  an arbitrarily large body before per-field validation ever runs. This
  only covers the declared `Content-Length` - a request that omits it
  (chunked transfer-encoding) is not covered; a real deployment behind a
  reverse proxy should also set a body-size limit there.

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

## Phase 8 findings

- **Dependency vulnerabilities (`pip-audit`).** Found 25 known
  vulnerabilities across `starlette` 0.46.2 (the one actually exposed on
  the API's request path), `setuptools` 65.5.0, and `pytest` 8.4.2.
  Fixed by bumping `fastapi`/`starlette`/`pytest`/`pytest-asyncio`/
  `setuptools`; `pip-audit` now reports zero known vulnerabilities. No
  dependency pinning or lock file existed before this beyond
  `pyproject.toml`'s version ranges - there's still no lock file
  (`pip install -e .` resolves against whatever's current on PyPI at
  install time), so a vulnerability introduced by a new release inside
  an existing range wouldn't be caught until the next manual
  `pip-audit` run; nothing here runs it in CI yet.
- **Error responses (verified, not changed).** `api/errorHandlers.py`'s
  catch-all `Exception` handler logs the real exception server-side
  (`logger.exception`) but always returns a fixed, generic message to
  the client - no stack trace, no exception type, no internal
  identifiers ever reach the response body. Domain errors return their
  own deliberately-written user-facing message, not an internal detail.
- **Log sanitization (verified, not changed).** The worker's per-task
  log lines (`workers/worker.py`) carry only `task_id`, `worker_id`,
  `correlation_id`, `attempt_number`, `outcome`, and `error_code` -
  never the task's payload or its full error message (those are
  persisted to the DB for operator inspection via the dead-letter API,
  not written to the log stream).
- **Path traversal on `processFile`.** `ProcessFilePayload.isSafeFileName`
  existed as a check the worker used, but nothing enforced it at
  submission - a `fileName` like `"../../etc/passwd"` was accepted with
  `201` and only failed later inside the worker (safely, via the
  filesystem-level `resolveProcessFilePath` containment check, but
  still after occupying a queue slot and an attempt). Fixed: a
  `field_validator` now rejects it at submission with `422`. The
  worker's own filesystem-level check is kept as the real
  defense-in-depth layer, since a payload could in principle be
  constructed bypassing pydantic validation (e.g. `model_construct`).
- **Request/connection timeouts and body size limits.** Added - see the
  trust-boundaries bullets above. The request-timeout and
  max-body-size middleware had no tests before this; both now have
  unit tests (`tests/unit/test_middleware.py`).
- **Admin auth (reviewed, not changed).** Already sound:
  `secrets.compare_digest` (timing-safe), tested for missing and wrong
  tokens (`tests/integration/test_dead_letters_api.py`). The
  shared-token, no-per-client-audit limitation noted above is unchanged
  and still the right thing to flag, not fix, at this project's scope.
