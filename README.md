# PulseQueue

A distributed task processing and reliability platform: clients submit
tasks over HTTP, PostgreSQL durably records them, and independent
worker processes execute them concurrently with bounded retries,
idempotent submission, and crash recovery.

**Status: Phase 0 — architecture and environment setup. No application
code, API, or Docker stack exists yet.** The table at the bottom of this
file tracks implementation status phase by phase and will be kept
honest as work lands; nothing here should be read as "working" until
its row says so.

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
- Docker Desktop (or Docker Engine + Compose) — **not yet verified on
  this machine**; required starting Phase 2 for PostgreSQL and Redis.
  Install from <https://docs.docker.com/get-docker/>, then confirm with:

  ```bash
  docker compose version
  ```

- Git and GitHub CLI (`gh`), if you intend to push changes or interact
  with Actions/PRs.

## Setup (current state: dependency installation only)

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install --upgrade pip
pip install -e ".[dev]"
```

This has been run and verified on this machine (see
[ADR 0000](docs/decisions/0000-acceptance-criteria.md) for the exact
commands and output). There is no application to start yet — `main.py`,
the database schema, and the worker entry point land in Phase 1–2.

## Environment variables

See [`.env.example`](.env.example) for every variable the application
will read (PostgreSQL/Redis connection info, admin token, worker
concurrency and lease duration, retry policy defaults). Copy it to
`.env` for local development; never commit a real `.env`.

## Migrations

Not yet implemented. Phase 1 adds Alembic migrations under
`migrations/`; this section will be updated with the actual commands
(`alembic upgrade head`, etc.) once they exist.

## Running the stack

Not yet implemented. Phase 2 adds `docker-compose.yml` (PostgreSQL +
Redis) and a worker entry point; Phase 9 finalizes a one-command local
startup. This section will be rewritten against the real Compose file.

## Running tests

Not yet implemented — no tests exist yet. Once they do:

```bash
pytest
```

will be the documented entry point, with integration/concurrency/
recovery tests marked so they can be skipped when Docker is
unavailable.

## API

Not yet implemented. See [`docs/api.md`](docs/api.md) (currently a
placeholder) and the full contract in
[`PROJECT_PLAN.md`](PROJECT_PLAN.md) section 7.

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

- **Docker is not installed on this development machine.** Everything
  from Phase 2 onward (Redis, PostgreSQL, full integration/concurrency/
  recovery tests, CI's service containers) is blocked until it is
  installed. The exact check and command to confirm once it is
  available: `docker compose version`.
- No application code exists yet (Phase 0 is architecture and
  environment setup only).
- No CI pipeline exists yet (Phase 5).
- No benchmark results exist yet (Phase 7) — none will be claimed until
  measured and committed with their exact configuration.

## Implementation status

| Phase | Scope | Status |
|---|---|---|
| 0 | Architecture, ADRs, repo/environment setup | **In progress (this commit)** |
| 1 | API, domain model, PostgreSQL persistence, migrations, tests | Not started |
| 2 | Redis integration, worker execution, task claiming | Not started |
| 3 | Idempotency, retries, leases, dead-letter handling, recovery | Not started |
| 4 | Pagination, filtering, cancellation, API quality | Not started |
| 5 | Comprehensive tests and GitHub Actions CI | Not started |
| 6 | Health checks, metrics, structured logs, runbook | Not started |
| 7 | Load testing, profiling, benchmark report | Not started |
| 8 | Security hardening and threat model | Not started |
| 9 | Packaging, documentation, demo, final review | Not started |

See [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for the full specification and
[`docs/decisions/`](docs/decisions/) for architecture decision records.
