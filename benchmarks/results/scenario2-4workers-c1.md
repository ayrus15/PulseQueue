# Benchmark result: 4 worker processes, concurrency=1 each

Same Locust parameters, same workload mix, same machine, run
immediately after truncating the database again for a clean baseline -
the only thing changed from `scenario1-1worker-c1.md` is the number of
worker processes (1 → 4; each still `PULSEQUEUE_WORKER_CONCURRENCY=1`,
so this tests worker *processes*, not in-process concurrency).

## Command

```bash
uvicorn pulsequeue.main:app --port 8021

# 4 separate processes, each:
PULSEQUEUE_WORKER_CONCURRENCY=1 python -m pulsequeue.workers.worker

locust -f benchmarks/locustfile.py --host http://127.0.0.1:8021 \
  --headless -u 20 -r 5 -t 60s \
  --csv benchmarks/results/scenario2-4workers-c1
```

## Environment

Identical to `scenario1-1worker-c1.md`: Intel i5-8250U (4 cores/8
threads), ~3.9 GB RAM, Windows 11, Python 3.11.9, PostgreSQL 18.6,
Redis 8.10.3, no Docker/container isolation - API, all 4 workers,
PostgreSQL, Redis, and Locust shared this one machine's resources.

## Results (raw CSVs alongside this file)

| Metric | 1 worker (scenario 1) | 4 workers (this run) | Change |
|---|---|---|---|
| Total requests (60s) | 1849 | 2484 | +34% |
| Failures | 0 | 0 | - |
| Aggregate throughput | 35.04 req/s | 42.02 req/s | **+20%** |
| POST p50 | 420 ms | 200 ms | **-52%** |
| POST p95 | 1300 ms | 1600 ms | **+23% (worse)** |
| POST max | 1594 ms | 2213 ms | **+39% (worse)** |
| GET /tasks/{id} p50 | 160 ms | 68 ms | -58% |

## From `/metrics`, captured immediately after the run

- `pulsequeue_tasks_submitted_total` / `_completed_total`: 1121 / 1121
  (100%, zero backlog - same as scenario 1)
- `pulsequeue_task_execution_seconds_sum/_count`: 4.445s / 1121 →
  **~3.97 ms average** (essentially identical to scenario 1's ~3.69 ms -
  as expected, 4x the claim loops doesn't change how long a single
  handler invocation takes)
- `pulsequeue_task_queue_wait_seconds_sum/_count`: 298.14s / 1121 →
  **~266 ms average** (down from ~297.5 ms - only a ~10% improvement,
  not the ~75% a naive "4 workers should quarter the wait" guess would
  predict)

## What changed, and what that actually means

Going from 1 to 4 worker processes:

- **Median latency improved a lot** (POST p50 halved, GET p50 more
  than halved) - with 4 independent pollers instead of 1, a newly
  submitted task is much more likely to be claimed almost immediately
  by *whichever* worker's poll/Redis-wake fires next.
- **Throughput improved only ~20%**, nowhere near the ~4x more worker
  processes would suggest if claiming were the only constraint.
- **Tail latency got measurably worse** (p95 and max both up over
  20%), not better.
- **Average handler execution time didn't move** - confirms the
  handlers themselves aren't the bottleneck at either worker count,
  consistent with scenario 1.

That combination - better median, flat-ish throughput, worse tail -
is not what "more claim loops relieve a claim-latency bottleneck"
alone would predict (that should improve *all* of throughput, median,
*and* tail together). The more consistent explanation: **this
single shared machine's own resources became the real constraint**
once 4 extra Python processes (each running an asyncio event loop,
a database connection, and a Redis connection) started competing with
the API, PostgreSQL, Redis, and Locust itself for the same 4 CPU
cores and ~3.9 GB of RAM. More workers polling concurrently also means
more concurrent `SELECT ... FOR UPDATE SKIP LOCKED` + `UPDATE`
round-trips hitting PostgreSQL per unit time (each worker still claims
one row at a time - `batchSize=1` - so 4 workers means 4x the
transaction *count*, not 4x the useful work per transaction), which
would show up exactly as "some requests get served faster, but the
slowest ones get slower" as PostgreSQL and the OS scheduler juggle
more concurrent short transactions on hardware that was never meant to
run five Python processes, a database, a cache, and a load generator
at once.

**This was not confirmed with CPU/memory profiling during the run** -
no profiler or resource monitor was attached while Locust ran, so the
"shared-machine contention" explanation above is the best-supported
reading of the measured numbers, not a directly observed fact. A real
next step (not done here) would be running the same comparison with
`psutil`/Task Manager sampling CPU and memory during each run, or
better, on separate machines/containers so the worker count is the only
variable actually changing.

## Bottleneck conclusion (PROJECT_PLAN.md Phase 7's required deliverable)

At this workload and on this hardware, **worker count is not the
limiting factor past 1 process** - execution time stays flat, and
throughput/tail latency don't scale with worker count the way pure
claim-contention would predict. The more defensible conclusion from
what was actually measured: **this benchmark is resource-constrained
by the single shared machine, not by anything in PulseQueue's own
design** (batchSize=1 claiming is a plausible secondary contributor
given the transaction-count math above, but isolating it from plain
hardware contention would need the machine-separation test described
above, which wasn't run). Do not read "4 workers" as this project's
recommended production configuration from this data alone - it's
simply what was tested, on hardware this test does not claim
represents any real deployment target.
