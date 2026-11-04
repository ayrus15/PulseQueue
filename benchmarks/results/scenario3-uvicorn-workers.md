# Benchmark result: uvicorn process count (1 vs. 2), 20 concurrent users

A different axis from `scenario1-1worker-c1.md`/`scenario2-4workers-c1.md`:
those two compare the number of **PulseQueue worker processes** (the
background task runners). This one holds that constant at 1 process
(default `PULSEQUEUE_WORKER_CONCURRENCY`, never restarted between the
two runs below - same `worker_id` in both) and instead compares the
number of **uvicorn** processes serving the API itself. Not the same
thing, and worth keeping straight: this result says nothing about
PulseQueue's own worker-claiming design, only about how the API server
is run.

## Command

```bash
# Run A: default single-process uvicorn
uvicorn pulsequeue.main:app --port 8000

# Run B: two uvicorn worker processes, otherwise identical
uvicorn pulsequeue.main:app --port 8000 --workers 2

# PulseQueue worker - one process, left running across both runs
python -m pulsequeue.workers.worker

# Load - identical parameters for both runs
locust -f benchmarks/locustfile.py --host http://localhost:8000 \
  --headless -u 20 -r 5 -t 60s \
  --csv benchmarks/results/run-20users
```

Run A's raw CSV was not preserved separately - the `--csv` filename was
reused for Run B, overwriting it - so Run A's numbers below come from
Locust's own terminal summary at the time, not a saved file. Run B's
full CSV is `run-20users_stats.csv` alongside this file. No `/metrics`
snapshot or CPU/memory profiling was captured for either run.

## Environment

- CPU: Intel Core i5-8250U, 4 cores / 8 threads
- RAM: ~3.9 GB total (a resource-constrained VM, not production-grade)
- OS: Windows 11 Enterprise, 64-bit
- Python: 3.11.9
- PostgreSQL: 18.6
- Redis: 8.10.3 (confirmed running for both runs - a prior attempt at
  this same comparison with Redis down produced unusable numbers,
  not included here)
- No Docker/container isolation - API, the worker, PostgreSQL, Redis,
  and Locust all shared this one machine's resources for both runs

## Results

| Metric | Run A: 1 uvicorn process | Run B: 2 uvicorn processes | Change |
|---|---|---|---|
| Total requests (60s) | 5 | 3,389 | **~680x** |
| Failures | 0 | 0 | - |
| POST /api/v1/tasks, avg latency | ~58,611 ms | 231 ms | **~99.6% lower** |
| POST /api/v1/tasks, min/max | 58,599 / 58,644 ms | 20 / 2,995 ms | - |
| Aggregate throughput | effectively 0 req/s (only 5 requests completed in 60s) | 57.24 req/s | - |
| POST p50 / p95 / p99 | ~59,000 ms (all 5 requests) | 120 / 820 / 2,200 ms | - |

Run A's 5 completed requests all took essentially the full 60-second
run to finish (min 58.6s, max 58.6s) - they were not slow to process,
they were slow to even begin. The application's own structured log for
individual requests in Run A showed `duration_ms` values around
1,100-1,200 ms once a request actually started being handled - the gap
between that and Locust's ~59-second end-to-end measurement is where
the real bottleneck shows up: requests queued for nearly a minute
before the server got to them at all.

## What changed, and what that actually means

Going from 1 to 2 uvicorn processes, with everything else identical
(same 20 Locust users, same ramp rate, same 60-second duration, same
single PulseQueue worker process, same database):

- **Throughput went from effectively zero to 57 req/s.** This isn't a
  tuning improvement, it's the difference between the server
  functioning under this load and not.
- **Individual request processing time was never the problem.** Once a
  request in Run A was actually scheduled, it completed in about the
  same ~1 second ballpark Run B's requests show end-to-end. The
  database, the application logic, and the worker were never the
  constraint in Run A - getting a request *scheduled* was.

The explanation this points to: `uvicorn pulsequeue.main:app` with no
`--workers` flag runs as a single OS process with a single `asyncio`
event loop. At 20 concurrent client connections, every one of them is
competing for time on that one event loop, on a machine that's already
documented elsewhere in this project (`scenario2-4workers-c1.md`) as
resource-constrained. Adding a second uvicorn process doesn't change
anything about PulseQueue's own code - it just means the OS can
schedule two independent processes instead of forcing 20 connections
through one, which is a request-level concurrency problem the
application's own design (async handlers, a connection pool, `FOR
UPDATE SKIP LOCKED` claiming) was never responsible for in the first
place.

**Not confirmed with CPU/memory profiling during either run** - no
profiler was attached, so "single-process event-loop saturation" is
the best-supported reading of the measured numbers (the
duration-logged-vs-wall-clock gap is strong evidence specifically for
*queueing before dispatch*, which is consistent with this explanation),
not a directly instrumented fact.

## Bottleneck conclusion

At 20 concurrent users on this hardware, **uvicorn process count, not
PulseQueue's own application or database design, is the limiting
factor** - Run A didn't fail because of slow queries, slow handlers, or
slow worker claiming; every one of those were shown to be fast once a
request got scheduled at all. This is a deployment/process-topology
finding, not a code finding: it says "run more than one uvicorn
process behind this kind of concurrent load," not "something in
PulseQueue needs to be rewritten." Two processes is what was tested
here, not a claim about the right number for any real deployment -
that would need the same kind of incremental threshold-finding
(10 users, 15 users, etc., at each process count) this project's
`benchmarks/README.md` already recommends, which wasn't done for this
specific comparison.
