# PulseQueue

[![CI](https://github.com/ayrus15/PulseQueue/actions/workflows/ci.yml/badge.svg)](https://github.com/ayrus15/PulseQueue/actions/workflows/ci.yml)

**Live:** [pulsequeue-api-ueyd.onrender.com/ui/](https://pulsequeue-api-ueyd.onrender.com/ui/) -
deployed on Render + Supabase + Upstash, see
[`docs/deployment.md`](docs/deployment.md). Free-tier hosting, so the
first request after a period of idle can take 30-60s to wake up.

A distributed task processing and reliability platform: clients submit
tasks over HTTP, PostgreSQL durably records them, and independent
worker processes execute them concurrently with bounded retries,
idempotent submission, and crash recovery.

**Status: all 9 phases done, plus a live deployment and a dashboard
built afterward.** Docker Compose, an architecture diagram, a real
failure-recovery walkthrough, a runnable demo script, and the
filled-in final acceptance checklist landed in Phase 9 - see
[`docs/finalReview.md`](docs/finalReview.md) for exactly what was
verified there and what wasn't (Docker itself was never run on this
development machine; no video, only a runnable script). Since then: a
static dashboard at `/ui` (see "Dashboard" below), a real bug the
dashboard surfaced and fixed - requeuing a dead-lettered task twice
could crash the worker on an attempt-numbering collision, see
`src/pulsequeue/persistence/models.py`'s `totalAttemptCount` for the
fix - and the live deployment linked above, itself how several real,
now-documented deployment gotchas were actually found
(`docs/deployment.md`). **214 tests pass (94.65% coverage)** - this is
the current, authoritative figure; every other count in this file is
intentionally historical, labeled with the phase it was measured at -
confirmed on GitHub Actions' own runners, including a dependency
vulnerability scan. The table at the bottom of this file tracks
implementation status phase by phase and will be kept honest as work
lands; nothing here should be read as "working" until its row says so.

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

## Architecture

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
[`docs/architecture.md`](docs/architecture.md) for a Mermaid system
diagram, the full request-flow sequence diagram, the state machine, and
delivery guarantees.

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
- **CI:** GitHub Actions (`.github/workflows/ci.yml` - see "Continuous integration" below)

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

There are two ways to run PulseQueue: Docker Compose (one command, no
local PostgreSQL/Redis install) or a local virtualenv against
PostgreSQL/Redis you run yourself. The virtualenv path is what every
test run and benchmark in this repository actually used, since Docker
isn't installed on the development machine this project was built on
(see "Current limitations" below) - the `docker-compose.yml` and
`Dockerfile` are real and reviewed, but `docker compose up` itself has
not been run end-to-end on this machine. If you have Docker, that path
should work as written; please open an issue if it doesn't.

### Option A: Docker Compose

```bash
docker compose up --build
```

This starts PostgreSQL and Redis, runs migrations once (the `migrate`
service), then starts the API on `http://localhost:8000` and a worker.
`docker compose down -v` tears it down including the database volume.

### Option B: local virtualenv

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install --upgrade pip
pip install -e ".[dev]"
```

Verified on this machine — see
[ADR 0000](docs/decisions/0000-acceptance-criteria.md) for the exact
commands and output. Run the API and worker directly, each against a
PostgreSQL database reachable at `DATABASE_URL` (see `.env.example`),
after applying migrations (see "Migrations" below):

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

`docker compose up --build` (see "Setup" above) is the one-command
path. Without Docker, run the API and worker directly - also "Setup"
above - against a PostgreSQL instance you provide yourself, and
optionally Redis (the worker degrades gracefully without it).

## Running tests

```bash
pytest tests/unit          # no database required
pytest tests/integration   # requires PostgreSQL - see below
pytest                      # both
pytest --cov=pulsequeue --cov-report=term-missing   # with coverage, like CI
```

Integration tests need a real PostgreSQL database and **skip cleanly**
(not fail) if one isn't reachable, printing the exact command to set one
up. Verified against a real local PostgreSQL 18 + Redis 8, and
confirmed again on GitHub's own runners via CI (214 tests, 94.65%
coverage, 0 failures - unit, API integration, task claiming/concurrency
(including a real cancel-vs-claim race and a real concurrent-duplicate-
idempotency-submission test), worker end-to-end, lease recovery,
dead-letter admin, a Redis-unreachable-after-commit fault injection,
and an actual Alembic upgrade-from-empty/downgrade cycle):

```bash
# One-time setup (run as a Postgres superuser):
#   CREATE ROLE pulsequeue LOGIN PASSWORD 'change-me-locally';
#   CREATE DATABASE pulsequeue_test OWNER pulsequeue;
#   CREATE DATABASE pulsequeue_migrations_test OWNER pulsequeue;
set TEST_DATABASE_URL=postgresql+asyncpg://pulsequeue:change-me-locally@localhost:5432/pulsequeue_test
set MIGRATIONS_TEST_DATABASE_URL=postgresql+asyncpg://pulsequeue:change-me-locally@localhost:5432/pulsequeue_migrations_test
pytest
```

## Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every
push to `main` and every pull request: `ruff check`, `ruff format
--check`, `mypy --strict`, an import sanity check, then the full test
suite with coverage against real `postgres:18`/`redis:8` service
containers (`--cov-fail-under=85`, comfortably below the 94.65% this
suite actually measures), and now also a `pip-audit` dependency
vulnerability scan (Phase 8). Coverage XML is uploaded as a build
artifact. See the badge at the top of this file for current status.

## API

`POST /api/v1/tasks` (with optional `Idempotency-Key` support),
`GET /api/v1/tasks` (cursor-paginated, filterable by `status`/`taskType`),
`GET /api/v1/tasks/{taskId}`, `POST /api/v1/tasks/{taskId}/cancel`,
`GET /api/v1/dead-letters`, and `POST /api/v1/dead-letters/{taskId}/requeue`
(the last two admin-token protected) are all implemented. Every
response carries an `X-Correlation-Id` header (FR4), and
`POST /api/v1/tasks` can optionally be rate limited per client IP
(`PULSEQUEUE_RATE_LIMIT_ENABLED`, off by default - fails open if Redis
is unreachable). See [`docs/api.md`](docs/api.md) and the full target
contract in [`PROJECT_PLAN.md`](PROJECT_PLAN.md) section 7.

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

`GET /health/live` (process up, no dependency checks) and
`GET /health/ready` (PostgreSQL + Redis; only PostgreSQL's outage fails
readiness - ADR 0001/0002) are implemented. `GET /metrics` exposes
Prometheus-format task/queue counts and queue depth (computed fresh
from PostgreSQL on every scrape, not accumulated in-process - correct
across restarts and multiple instances), API request count/duration,
worker heartbeat age (via Redis), and genuine histograms for task
execution time and queue wait time built from real data. See
[`docs/operationsRunbook.md`](docs/operationsRunbook.md) for how to
read all of it, written against the actual implementation. No
Grafana/Prometheus server is set up here - nothing to screenshot
honestly - but any standard Prometheus scrape config pointed at
`/metrics` works as-is.

## Dashboard

A small static dashboard is served at `http://localhost:8000/ui/` once
the API is running - no separate process, no build step, just
`frontend/index.html` mounted read-only by the API itself
(`PULSEQUEUE_UI_DIRECTORY`, defaults to `frontend`; the API still runs
fine without this directory present, just without `/ui`). It submits
tasks, polls `GET /api/v1/tasks` for a live-updating table, parses
`GET /metrics` for the queue-depth stat cards, and has an admin-token-
gated dead-letter panel with requeue. Vanilla HTML/CSS/JS - see
`frontend/app.js` - talking to the same API documented below, nothing
more.

## Deployment

[`docs/deployment.md`](docs/deployment.md) covers deploying to the
cloud on a free-tier stack requiring no credit card anywhere: Render
(from this repo's own [`Dockerfile`](Dockerfile), via
[`render.yaml`](render.yaml)) for the API, the dashboard, and - via
`PULSEQUEUE_RUN_WORKER_IN_PROCESS` - the worker too, all in one free
service; Supabase for PostgreSQL; Upstash for Redis. Running the
worker in-process is a documented, logged deployment concession for
Render's lack of a free Background Worker tier (and GCP/Oracle's free
VM tiers still requiring a card) - not this project's real
architecture, which keeps the API and worker as genuinely independent
processes (see `docs/architecture.md`); the alternative path in
`docs/deployment.md` runs the worker separately on a free GCP VM
([`deploy/gcp/`](deploy/gcp/)) for anyone who'd rather have that and
doesn't mind the card. The repository owner deployed this for real on
Render - it's **live** (see the link at the top of this file) - which
is how several real gotchas got caught and fixed rather than guessed:
Render doesn't interpret shell syntax (`&&`, quotes) in its
`dockerCommand` field (use a real script file); Supabase's direct
connection is IPv6-only and doesn't resolve on Render's network (use
the Session pooler instead); `DATABASE_URL` needs the
`postgresql+asyncpg://` scheme Supabase doesn't give you by default;
and a password containing `@`/`%`/`$` needs percent-encoding, which in
turn broke Alembic's `ConfigParser`-based config in a way this project
now works around (`migrations/env.py`). The guide says what was
actually checked and what wasn't, rather than claiming more than was
verified.

## Demo

No recorded video exists. [`docs/demoScript.md`](docs/demoScript.md)
is a copy-pasteable walkthrough - submission, execution, retry, retry
exhaustion to dead-letter, admin requeue, and monitoring - with the
actual commands and actual output from a real run, runnable against
your own stack to see (or record) the same thing; the dashboard above
is the easier way to watch the same sequence happen live without typing
any of it. [`docs/operationsRunbook.md`](docs/operationsRunbook.md)'s
"Failure recovery walkthrough" covers the one scenario neither of
those does: a worker crashing mid-task.

## Benchmarks

[`benchmarks/`](benchmarks/README.md) holds the Locust workload
(`locustfile.py`) and two real, run results: 1 worker process vs. 4,
same load, same machine. Headline finding: going to 4 workers roughly
halved median latency but only grew throughput ~20% and made tail
latency *worse* - not what naive "more workers = proportionally more
throughput" would predict. The best-supported read of the numbers
(execution time stays flat either way; see
[`benchmarks/results/scenario2-4workers-c1.md`](benchmarks/results/scenario2-4workers-c1.md)
for the full reasoning) is that this single shared, resource-constrained
machine - not anything in PulseQueue's own design - was the limiting
factor in this test. Not claimed to represent any other hardware.

## Future work

Not limitations of the current design so much as scope that was
deliberately left out of this project's 9 phases:

- **Per-client authentication.** Admin access is currently one shared
  bearer token (`X-Admin-Token`) with no per-client identity or audit
  trail, and idempotency keys share one constant scope - see
  `docs/threatModel.md`. Real multi-tenant auth (API keys or OAuth per
  client, idempotency scoped per client) is the natural next step
  before exposing this beyond a single trusted operator.
- **Horizontal worker scaling beyond one machine.** Nothing in the
  design prevents it (workers only coordinate through PostgreSQL), but
  it's never been tried - Phase 7's benchmark ran 1 vs. 4 *processes*
  on one machine, not workers across multiple hosts.
- **A sliding-window or token-bucket rate limiter.** The current
  limiter (`api/rateLimit.py`) is a simple fixed window, documented as
  intentionally not production-grade.
- **Automatic retry of a failed request at the API layer** for a
  PostgreSQL connection failure mid-request (see
  `docs/operationsRunbook.md`'s fault-scenario table) - today the
  client sees a `500` and retries itself.
- **A real Grafana/Prometheus observability dashboard.** `/metrics` is
  real Prometheus output (see "Monitoring" above); nothing renders it
  as graphs. Not to be confused with the task-management dashboard at
  `/ui` (see "Dashboard" above), which is real, built, and live - this
  item is specifically about metrics visualization/alerting, which
  doesn't exist.

## Current limitations

- **Docker is still not installed** on this development machine.
  PostgreSQL 18 and Redis 8 were both installed directly instead (via
  Chocolatey, run elevated by the repository owner since this session
  can't self-elevate) and are what the commands above and the test
  suite were actually run against. `docker compose version` is the
  command to confirm Docker once it's installed. `Dockerfile` and
  `docker-compose.yml` (Phase 9) exist and have been reviewed, and
  `pip install .`, `import pulsequeue.main`, and the `alembic` CLI were
  each verified in an isolated clean virtualenv built from exactly what
  the image installs - but `docker build`/`docker compose up`
  themselves have not been run on this machine. If you have Docker and
  the stack doesn't come up as documented, please open an issue.
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
- `redis-server.exe` here is a bare process, not a registered Windows
  service - it doesn't survive a reboot or even always stay up across
  this machine's sessions, and had to be restarted mid-Phase-4 after it
  had stopped. In a real deployment this is Docker Compose's job
  (Phase 9) or a proper service; noted here as an actual limitation
  observed, not a hypothetical one.
- The Phase 7 benchmark ran on one shared, resource-constrained machine
  (4 cores, ~3.9 GB RAM) with no CPU/memory profiler attached during
  the run - the "this machine is the bottleneck" conclusion is the
  best-supported reading of the measured latency/throughput numbers,
  not a directly observed fact. See
  `benchmarks/results/scenario2-4workers-c1.md` for exactly what was
  and wasn't measured.

## Implementation status

Test/coverage figures in this table are **point-in-time** - exactly
what that phase measured the day it was completed, not updated
retroactively as later phases added more tests. For the current count,
see the status line at the top of this file (214 tests, 94.65%
coverage) - that is the only number meant to answer "how many tests
does this have right now."

| Phase | Scope | Status |
|---|---|---|
| 0 | Architecture, ADRs, repo/environment setup | Done |
| 1 | API, domain model, PostgreSQL persistence, migrations, tests | Done |
| 2 | Redis integration, worker execution, task claiming | Done |
| 3 | Idempotency, retries, leases, dead-letter handling, recovery | Done |
| 4 | Pagination, filtering, cancellation, API quality | Done |
| 5 | Comprehensive tests and GitHub Actions CI | Done — confirmed green on GitHub's own runners (badge above) |
| 6 | Health checks, metrics, structured logs, runbook | Done — 198/198 tests at the time, 91% coverage; a live smoke test caught and fixed a real negative-duration bug in the queue-wait histogram before it shipped |
| 7 | Load testing, profiling, benchmark report | Done — 2 real scenarios (1 vs. 4 workers), bottleneck conclusion in `benchmarks/results/` |
| 8 | Security hardening and threat model | Done — see `docs/threatModel.md`'s "Phase 8 findings"; 208/208 tests at the time, 91% coverage |
| 9 | Packaging, documentation, demo, final review | Done — see [`docs/finalReview.md`](docs/finalReview.md) for the filled-in acceptance checklist and what's genuinely not done |

See [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for the full specification and
[`docs/decisions/`](docs/decisions/) for architecture decision records.
