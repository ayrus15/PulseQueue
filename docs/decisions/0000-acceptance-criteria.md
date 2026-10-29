# ADR 0000: Phase 0 acceptance criteria and environment baseline

**Status:** Accepted

## Purpose

Record what "done" means for Phase 0, and the verified state of the
local environment, so later phases build on checked facts instead of
assumptions.

## Phase 0 acceptance criteria

A reviewer can, from this repository alone:

- Understand what PulseQueue does and explicitly does not do
  (`README.md`, `PROJECT_PLAN.md`).
- Understand the four foundational design decisions and their
  trade-offs (`docs/decisions/0001`–`0004`).
- See the target architecture, API contract, data model, and state
  machine (`docs/architecture.md`, `PROJECT_PLAN.md` sections 6–8).
- Reproduce the local Python environment this plan was validated
  against (below) and know exactly what is still missing to run the
  full stack (Docker).

No application code, tests, or Docker services are expected to exist
yet — this phase is architecture and environment setup only.

## Verified environment (2026-10-29)

Commands actually run, and their results:

```
py -3.11 --version
# Python 3.11.9

py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
# pip 24.0 -> 26.2.2, succeeded

.venv\Scripts\python.exe -m pip install \
  "fastapi>=0.115,<0.116" "uvicorn[standard]>=0.32,<0.33" \
  "sqlalchemy[asyncio]>=2.0,<2.1" "asyncpg>=0.29,<0.30" \
  "alembic>=1.13,<1.14" "pydantic>=2.9,<3" "pydantic-settings>=2.5,<3" \
  "redis>=5.0,<6" "python-json-logger" "prometheus-client>=0.20,<0.21"
# All 30 packages installed successfully, no build failures.

.venv\Scripts\python.exe -m pip install \
  "pytest>=8.3,<9" "pytest-asyncio>=0.24,<0.25" "httpx>=0.27,<0.28" \
  "ruff>=0.7,<0.8" "mypy>=1.13,<1.14"
# All installed successfully.
```

Findings:

- The machine's PATH-default `python`/`py` resolves to a broken
  `C:\Python313` install (directory exists but `python.exe` is missing).
  `py -3.11` resolves to a working Store install of Python 3.11.9 and is
  what this project targets (`requires-python = ">=3.11,<3.13"` in
  `pyproject.toml`). Anyone continuing this project on this machine
  should use `py -3.11` explicitly rather than bare `python`, or fix the
  3.13 install.
- **Docker is not installed on this machine.** `docker --version` and
  `docker compose version` both fail with "command not found." This
  blocks Phase 2 onward (Redis/PostgreSQL via Compose, CI's local
  reproduction) until Docker Desktop (or an equivalent, e.g. Docker
  Engine on WSL2) is installed. The exact blocked check and its command
  are listed in `README.md`'s "Current limitations" section.
- GitHub CLI (`gh`) is authenticated as `ayrus15` with `repo` and
  `workflow` scopes, sufficient for pushing commits and configuring
  Actions later.
- The GitHub repository `ayrus15/PulseQueue` already exists and was
  empty prior to this commit.

## Repository location note

This project's working directory (`C:\Users\VAMSI\NewProjects\PulseQueue`)
is nested inside `C:\Users\VAMSI\NewProjects`, which is itself an
unrelated git repository (remote: `ayrus15/Enterprise_Performance_Project`)
with its own pending, uncommitted changes. PulseQueue was initialized as
its own independent git repository (`git init` inside this directory,
`origin` pointing at `ayrus15/PulseQueue`) and never touches the parent
repository's history, working tree, or remote.
