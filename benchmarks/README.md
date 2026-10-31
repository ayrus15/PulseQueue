# Benchmarks

**Status: Phase 7 done.** Two scenarios run (1 worker vs. 4 worker
processes, otherwise identical), compared, and written up with a
bottleneck conclusion in `results/scenario2-4workers-c1.md`. This file
is the methodology and exact reproduction commands; `locustfile.py` is
the workload; `results/` holds the dated, environment-specific result
reports and their raw Locust CSVs.

## What this measures

`locustfile.py` drives `POST /api/v1/tasks` (a mix of `generateReport`,
`calculateMetrics`, `sendNotification`, each with a fresh
`Idempotency-Key` - so this measures fresh-task throughput, not the
idempotency fast path) followed by `GET /api/v1/tasks/{taskId}`, plus
occasional `GET /api/v1/tasks` listing calls. It does **not** measure
worker throughput directly - Locust only talks to the API. Worker
throughput is read from `/metrics` (`pulsequeue_tasks_completed_total`'s
rate of change, and `pulsequeue_queue_depth{status="queued"}`) and from
querying PostgreSQL directly, both captured before and after each run.

## Prerequisites

```bash
pip install -e ".[benchmark]"   # installs locust
```

A running PostgreSQL + Redis (see README.md's "Setup"), with migrations
applied (`alembic upgrade head`) and - for a clean baseline - no
leftover rows from manual testing:

```bash
psql -U pulsequeue -d pulsequeue -c "TRUNCATE task_attempts, idempotency_records, tasks;"
```

## Running one scenario

```bash
# Terminal 1: the API
uvicorn pulsequeue.main:app --port 8000

# Terminal 2: N worker processes (see results/ for which N was used per run)
python -m pulsequeue.workers.worker

# Terminal 3: the load generator, headless, for a fixed duration
locust -f benchmarks/locustfile.py --host http://localhost:8000 \
  --headless -u 20 -r 5 -t 60s \
  --csv benchmarks/results/<scenario-name>
```

`-u 20 -r 5` means 20 simulated users, ramping up 5 at a time per
second; `-t 60s` runs for 60 seconds. Locust's own summary (printed to
stdout and written to `<scenario-name>_stats.csv`) gives requests/sec,
p50/p95/p99 latency, and failure count directly - no need to compute
these by hand.

## Comparing worker counts

Run the exact same Locust invocation twice, changing only the worker
side between runs (restart the worker process(es) with a different
`PULSEQUEUE_WORKER_CONCURRENCY`, or start multiple worker processes),
and record both under `results/` with the worker configuration named in
the filename. Everything else (API, Locust parameters, task payload
mix) must stay identical between the two runs being compared, or the
comparison isn't valid.

## Rules this project follows (PROJECT_PLAN.md section 13)

- No invented throughput numbers - every number in `results/` came from
  an actual Locust run or an actual `/metrics`/SQL query, both captured
  in the result file alongside the numbers.
- Every result file states the exact environment (CPU, RAM, OS, Python,
  PostgreSQL/Redis versions, worker configuration) and the exact command
  that produced it.
- Results from this machine are not claimed to represent production
  scale or any other hardware - see each result file's "Environment"
  section for what was actually used, including real constraints (this
  machine has 4 cores / ~3.9 GB RAM, not production-grade, and no
  Docker, so there is no container isolation between the API, worker,
  PostgreSQL, Redis, and Locust all sharing the same machine's
  resources during a run - that itself is a result-shaping constraint
  worth stating explicitly, not just a footnote).
