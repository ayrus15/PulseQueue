# PulseQueue

A distributed task processing and reliability platform: clients submit
tasks over HTTP, PostgreSQL durably records them, and independent
worker processes execute them concurrently with bounded retries,
idempotent submission, and crash recovery.

**Status: Phase 3 done — idempotent submission, bounded exponential
backoff with jitter, permanent-vs-retryable error classification,
worker lease-expiry recovery, and admin-protected dead-letter
inspection/requeue all exist and are tested (151 tests) against real
PostgreSQL 18 and Redis 8. Pagination/filtering/cancellation (Phase 4)
and everything after do not exist yet.** The table at the bottom of
this file tracks implementation status phase by phase and will be kept
honest as work lands; nothing here should be read as
"working" until its row says so.

## Why this exists

Background work (sending a report, processing a file) shouldn't block
an HTTP request, but moving it to a queue introduces real engineering
problems: duplicate client requests, crashed workers, competing
workers, retries that need to be bounded, and tasks that must not
silently vanish on a restart. PulseQueue is a small, deliberately scoped
system built to handle those problems predictably and to document what
it does and does not guarantee — see
[`docs/architecture.md`](docs/architecture.md) and
[`docs/decisions/`](docs/decisions/) for the reasoning, and
[`PROJECT_PLAN.md`](PROJECT_PLAN.md) for the full specification this
project is built against.

## Architecture (planned)

```
Client --HTTP--> FastAPI API --writes--> PostgreSQL (source of truth)
                                   |
                                   +--notifies (best-effort)--> Redis
                                                                   |
                      Worker process(es) <--poll PostgreSQL--------+
                           |
                           +--records attempts/results--> PostgreSQL
```

PostgreSQL is authoritative for task state; Redis only shortens how
long an idle worker waits before it notices new work. See
[ADR 0002](docs/decisions/0002-redis-role-and-recovery.md) for why, and
[`docs/architecture.md`](docs/architecture.md) for the full request flow
and state machine.

## Technology stack

- **Language:** Python 3.11
- **API:** FastAPI + Uvicorn
- **Persistence:** PostgreSQL via SQLAlchemy 2.0 (async) + asyncpg,
  migrations via Alembic
- **Coordination:** Redis (latency optimization only — see ADR 0002)
- **Validation:** Pydantic v2
- **Observability:** `prometheus-client`, structured JSON logs
  (`python-json-logger`)
- **Testing:** pytest, pytest-asyncio, HTTPX
- **Quality:** Ruff (lint + format), mypy (strict)
- **Packaging/runtime:** Docker Compose
- **CI:** GitHub Actions (not yet configured — Phase 5)

Dependency versions are pinned in [`pyproject.toml`](pyproject.toml).

## Prerequisites

- Python 3.11 or 3.12. On this development machine, the PATH-default
  `python`/`py` pointed at a broken Python 3.13 install; `py -3.11` was
  used instead and is recommended until that's fixed locally — see
  [ADR 0000](docs/decisions/0000-acceptance-criteria.md) for details.
- **Docker is still not installed on this development machine.**
  PostgreSQL 18 and Redis 8 were both installed directly instead (see
  "Current limitations"). Install Docker from
  <https://docs.docker.com/get-docker/>, then confirm with:

  ```bash
  docker compose version
  ```

- Git and GitHub CLI (`gh`), if you intend to push changes or interact
  with Actions/PRs.

## Setup

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install --upgrade pip
pip install -e ".[dev]"
```

Verified on this machine — see
[ADR 0000](docs/decisions/0000-acceptance-criteria.md) for the exact
commands and output. The Docker Compose stack (Phase 9) doesn't exist
yet; run the API and worker directly, each against a PostgreSQL
database reachable at `DATABASE_URL` (see `.env.example`):

```bash
uvicorn pulsequeue.main:app --reload
python -m pulsequeue.workers.worker
```

Interactive API docs are then at `http://localhost:8000/docs`. The
worker also tries to reach Redis (`REDIS_URL`) for low-latency wake-ups,
but runs correctly without it - see ADR 0002.

## Environment variables

See [`.env.example`](.env.example) for every variable the application
will read (PostgreSQL/Redis connection info, admin token, worker
concurrency and lease duration, retry policy defaults). Copy it to
`.env` for local development; never commit a real `.env`.

## Migrations

Alembic migrations live under `migrations/`, driven by
`src/pulsequeue/persistence/models.py`'s SQLAlchemy metadata (there is
no reliance on `create_all` in the running application — only tests use
it, for speed; see `tests/integration/conftest.py`).

```bash
# Uses DATABASE_URL from the environment if set, else alembic.ini's default.
alembic upgrade head
alembic downgrade base   # to tear back down
```

`tests/integration/test_migrations.py` runs this exact upgrade/downgrade
against a real database as part of the test suite.

## Running the stack

`docker-compose.yml` doesn't exist yet (Phase 9 finalizes a one-command
local startup). Until then, run the API and worker directly - see
"Setup" above - against a PostgreSQL instance you provide yourself, and
optionally Redis (the worker degrades gracefully without it).

## Running tests

```bash
pytest tests/unit          # no database required
pytest tests/integration   # requires PostgreSQL - see below
pytest                      # both
```

Integration tests need a real PostgreSQL database and **skip cleanly**
(not fail) if one isn't reachable, printing the exact command to set one
up. Verified against a real local PostgreSQL 18 + Redis 8 (151 tests,
0 failures - unit, API integration, task claiming/concurrency,
idempotency (including a real concurrent-duplicate-submission test),
worker end-to-end, lease recovery, dead-letter admin, and an actual
Alembic upgrade-from-empty/downgrade cycle):

```bash
# One-time setup (run as a Postgres superuser):
#   CREATE ROLE pulsequeue LOGIN PASSWORD 'change-me-locally';
#   CREATE DATABASE pulsequeue_test OWNER pulsequeue;
#   CREATE DATABASE pulsequeue_migrations_test OWNER pulsequeue;
set TEST_DATABASE_URL=postgresql+asyncpg://pulsequeue:change-me-locally@localhost:5432/pulsequeue_test
set MIGRATIONS_TEST_DATABASE_URL=postgresql+asyncpg://pulsequeue:change-me-locally@localhost:5432/pulsequeue_migrations_test
pytest
```

## API

`POST /api/v1/tasks` (with optional `Idempotency-Key` support),
`GET /api/v1/tasks/{taskId}`, `GET /api/v1/dead-letters`, and
`POST /api/v1/dead-letters/{taskId}/requeue` (the last two admin-token
protected) are implemented. Listing with pagination/filtering and
cancellation are Phase 4. See [`docs/api.md`](docs/api.md) and the full
target contract in [`PROJECT_PLAN.md`](PROJECT_PLAN.md) section 7.

## Worker

`python -m pulsequeue.workers.worker` runs `PULSEQUEUE_WORKER_CONCURRENCY`
independent claim/process loops against the registered handlers in
[`src/pulsequeue/workers/handlers.py`](src/pulsequeue/workers/handlers.py)
(`generateReport`, `calculateMetrics`, `processFile`, `sendNotification`,
`simulateFailure`), plus a recovery loop that returns tasks whose
worker lease expired back to `queued`. A failed attempt is requeued
with bounded exponential backoff (`PULSEQUEUE_RETRY_BASE_DELAY_SECONDS`/
`_MAX_DELAY_SECONDS`) if attempts remain; a `PermanentTaskError` (e.g.
`processFile`'s missing-file/unsafe-path errors) goes straight to
`failed` regardless of attempts left, and exhausting attempts on an
ordinary retryable error goes to `dead_letter`.

## Monitoring

Not yet implemented. Phase 6 adds `/metrics`, `/health/live`, and
`/health/ready`; see [`docs/operationsRunbook.md`](docs/operationsRunbook.md)
(currently a placeholder).

## Benchmarks

Not yet implemented. Phase 7 adds a Locust-based load test and
reproducible benchmark instructions under
[`benchmarks/`](benchmarks/README.md) — no results are claimed until
they are measured.

## Current limitations

- **Docker is still not installed** on this development machine.
  PostgreSQL 18 and Redis 8 were both installed directly instead (via
  Chocolatey, run elevated by the repository owner since this session
  can't self-elevate) and are what the commands above and the test
  suite were actually run against. `docker compose version` is the
  command to confirm Docker once it's installed.
- Redis's best-effort degradation path (ADR 0002) was also verified for
  real, not just claimed: the worker and API were run and tested with
  Redis genuinely unreachable before it was installed (logged
  warnings, no crash, no lost tasks), and the real notify/wait happy
  path was then verified once it was.
- `pytest tests/integration` **skips cleanly** (prints the exact setup
  command, doesn't report a false pass) if no database is reachable at
  `TEST_DATABASE_URL` - this is tested and confirmed working, not just
  intended.
- Idempotency keys share one constant scope (not per-client) until real
  authentication exists - see docs/threatModel.md.
- Pagination/filtering for `GET /api/v1/tasks` (there is no such
  endpoint yet) and cancellation do not exist yet (Phase 4).
- No CI pipeline exists yet (Phase 5).
- No benchmark results exist yet (Phase 7) — none will be claimed until
  measured and committed with their exact configuration.

## Implementation status

| Phase | Scope | Status |
|---|---|---|
| 0 | Architecture, ADRs, repo/environment setup | Done |
| 1 | API, domain model, PostgreSQL persistence, migrations, tests | Done |
| 2 | Redis integration, worker execution, task claiming | Done |
| 3 | Idempotency, retries, leases, dead-letter handling, recovery | Done — 151/151 tests pass against real PostgreSQL 18 and real Redis 8, including a genuine concurrent-duplicate-submission test and a simulated-dead-worker lease recovery test |
| 4 | Pagination, filtering, cancellation, API quality | Not started |
| 5 | Comprehensive tests and GitHub Actions CI | Not started |
| 6 | Health checks, metrics, structured logs, runbook | Not started |
| 7 | Load testing, profiling, benchmark report | Not started |
| 8 | Security hardening and threat model | Not started |
| 9 | Packaging, documentation, demo, final review | Not started |

See [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for the full specification and
[`docs/decisions/`](docs/decisions/) for architecture decision records.
