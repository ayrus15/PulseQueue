# PulseQueue: Distributed Task Processing and Reliability Platform

## Project Charter and Implementation Playbook

**Project type:** Portfolio grade software engineering project\
**Primary language:** Python\
**Target role:** Software Engineering Apprentice / Entry Level Software
Engineer\
**Planned duration:** 6 weeks at 3 to 4 focused hours per day\
**Deployment target:** Reproducible local environment using Docker
Compose\
**Status:** Project specification. No implementation or benchmark
results should be claimed until they exist.

------------------------------------------------------------------------

## 1. Project Overview

PulseQueue is a small distributed task processing platform. Clients
submit tasks through an HTTP API. The service validates and persists
each task, places it in a queue, and allows independent workers to
execute tasks concurrently. The system records task state and execution
attempts, retries eligible failures, isolates tasks that exhaust their
retry limit, and exposes operational metrics.

The goal is not to build a large commercial queue system. The goal is to
demonstrate disciplined engineering: clear requirements, maintainable
modules, safe state transitions, concurrency control, failure recovery,
automated testing, observability, performance measurement, and
reproducible setup.

### The problem

Background work often takes longer than a normal HTTP request.
Processing it inline can make APIs slow and fragile. A task queue
separates request acceptance from execution, but introduces engineering
challenges:

-   Requests may be retried by clients.
-   The same logical task may be submitted more than once.
-   Workers can crash while processing tasks.
-   Temporary dependencies may become unavailable.
-   Tasks may fail repeatedly.
-   Multiple workers may compete for work.
-   Queue depth and latency may increase without being noticed.
-   An accepted task must not silently disappear after a process
    restart.

PulseQueue should handle these cases predictably and document its
delivery guarantees and limitations.

### Primary engineering objectives

1.  Build a documented API with request validation and useful error
    responses.
2.  Implement task persistence and explicit lifecycle transitions.
3.  Process tasks asynchronously using independent workers.
4.  Prevent duplicate logical submissions through idempotency keys.
5.  Implement bounded retries, exponential backoff, and dead letter
    handling.
6.  Recover tasks left in an active state after worker failure.
7.  Provide structured logs, health checks, and useful metrics.
8.  Test correctness, concurrency, failure handling, and recovery
    automatically.
9.  Benchmark performance under a documented workload.
10. Make the project straightforward for another developer to run
    locally.

### Explicit non goals

Do not start with Kubernetes, microservices beyond the API and worker
processes, a complex frontend, a paid cloud deployment, machine
learning, or a custom message broker. Do not claim exactly once
execution. Do not add features before the reliability and testing
foundations work.

------------------------------------------------------------------------

## 2. Intended Users and Example Workloads

PulseQueue is a general background task platform. Use safe,
deterministic demo task handlers such as:

-   `generateReport`: produce a small report from supplied test data.
-   `sendNotification`: simulate notification delivery without sending
    real messages.
-   `processFile`: validate and summarize a small local test file.
-   `calculateMetrics`: calculate summary values from a test payload.
-   `simulateFailure`: deliberately fail based on a controlled test
    parameter, only in development and testing environments.

The task handlers must not execute arbitrary shell commands, evaluate
user supplied Python, or access arbitrary filesystem paths. Keep the
demo safe and deterministic.

Seed or example records may use the following names: Sachin Yadav, Hema
C, Arjun Ramesh, Shaurya Mishra, and Shubham Kundu. These names are
example data only and must not be represented as real customers or
users.

------------------------------------------------------------------------

## 3. Functional Requirements

### FR 1: Task submission

-   Accept a valid task type and JSON payload.
-   Accept an optional idempotency key.
-   Validate task type, payload shape, and payload size.
-   Persist the task before acknowledging successful acceptance.
-   Return a task ID, initial status, and status URL.
-   Return consistent validation errors for invalid requests.
-   Reject unsupported task types.

### FR 2: Task retrieval

-   Retrieve a task by ID.
-   Return status, timestamps, attempt count, and safe result metadata.
-   Do not expose secrets or internal stack traces through public API
    responses.
-   Return a clear not found response for unknown IDs.

### FR 3: Task listing

-   Support pagination using `limit` and `cursor` or a clearly
    documented page based approach.
-   Enforce a maximum page size.
-   Support optional status and task type filters.
-   Use deterministic ordering so records do not randomly shift between
    pages.
-   Add indexes that match common filters and ordering.

### FR 4: Cancellation

-   Allow cancellation of tasks that have not started.
-   Define what happens if a task is already running.
-   Do not claim a running task has been stopped unless the worker has
    actually cooperated.
-   Record cancellation time and final state.

### FR 5: Worker processing

-   Run workers separately from the API process.
-   Support configurable worker concurrency.
-   Record task start, completion, failure, and attempt information.
-   Prevent two workers from simultaneously owning the same active task
    through a reliable claim or lease mechanism.
-   Ensure worker shutdown is graceful where possible.

### FR 6: Retry policy

-   Retry only eligible failures.
-   Use bounded exponential backoff with configurable limits.
-   Add jitter to reduce synchronized retries.
-   Record attempt count and next eligible retry time.
-   Move exhausted tasks to a dead letter state or dead letter table.
-   Provide an administrative way to inspect and optionally requeue a
    dead letter task, with safeguards.

### FR 7: Idempotency

-   Scope idempotency keys appropriately, such as by client or tenant if
    authentication is implemented.
-   Store a stable relationship between the key and the original task.
-   Repeated requests with the same key and same logical request return
    the original task.
-   Reuse of the same key with a different payload returns a conflict
    response.
-   Enforce uniqueness in the database, not only in application code.
-   Test concurrent duplicate submissions.

### FR 8: Observability

Expose health and metrics for:

-   API and database connectivity.
-   Queue depth by state.
-   Tasks accepted, completed, failed, retried, and dead lettered.
-   Task execution duration.
-   Queue wait duration.
-   Worker heartbeat and availability.
-   API request count, latency, and error rate.

Metrics should avoid unbounded labels such as task IDs, arbitrary
payload values, or idempotency keys.

### FR 9: Configuration and security

-   Read configuration from environment variables.
-   Validate required configuration at startup.
-   Never commit secrets.
-   Use safe defaults for local development.
-   Restrict administrative operations.
-   Add authentication before exposing the service outside localhost.
-   Set request size limits and sensible timeouts.
-   Do not log full payloads if they could contain sensitive data.
-   Provide `.env.example` with placeholders only.

------------------------------------------------------------------------

## 4. Non Functional Requirements

### Correctness

-   Every task follows documented state transitions.
-   Invalid transitions are rejected.
-   A task accepted by the API is persisted before a success response is
    returned.
-   Concurrent workers cannot both claim the same task at the same time
    under normal operation.
-   Idempotency works even when duplicate requests arrive concurrently.

### Reliability

-   Temporary failures are retried within a configured limit.
-   Exhausted tasks remain inspectable.
-   The system can recover tasks whose worker lease expired.
-   A process restart does not silently erase accepted tasks.
-   All delivery guarantees and edge cases are documented.

### Maintainability

-   Separate API, domain logic, persistence, queueing, workers,
    configuration, and observability.
-   Use type hints and clear interfaces.
-   Keep functions focused and avoid large monolithic modules.
-   Use camelCase for function names to maintain consistent project
    style.
-   Use descriptive class names and constants.
-   Avoid unnecessary abstractions and dependencies.

### Performance

-   Measure throughput and latency instead of inventing targets.
-   Record hardware, operating system, Docker settings, workload,
    concurrency, and warm up duration.
-   Report p50 and p95 latency, throughput, failure rate, and queue wait
    time.
-   Compare single worker and multi worker runs.
-   Investigate bottlenecks before making optimization claims.

### Reproducibility

-   A new developer should be able to start the project from the README.
-   Tests must be runnable with documented commands.
-   CI must run core tests and quality checks.
-   Benchmark results must include the command and configuration needed
    to reproduce them.

------------------------------------------------------------------------

## 5. Architecture

### Logical components

1.  **FastAPI application:** validates requests, applies API rules, and
    returns responses.
2.  **Domain layer:** task models, state transitions, retry rules,
    idempotency decisions, and domain errors.
3.  **Persistence layer:** PostgreSQL access and transaction boundaries.
4.  **Queue adapter:** Redis backed task dispatch or wake up mechanism.
5.  **Worker process:** claims work, executes registered handlers,
    records results, and schedules retries.
6.  **Recovery process:** finds expired worker leases and safely
    requeues or marks tasks for recovery.
7.  **Observability layer:** structured logs, metrics, health checks,
    and request correlation.
8.  **Test and benchmark tools:** unit tests, integration tests, fault
    injection, and load generation.

### Important design decision: PostgreSQL is the source of truth

Persist task state in PostgreSQL. Redis should support dispatch and
coordination, but the system must be designed so a Redis restart does
not make the database forget accepted tasks. Implement a recovery or
polling mechanism that can rediscover eligible tasks. Explain the
tradeoff in the architecture decision records.

Do not assume that writing to PostgreSQL and Redis is one atomic
operation. Design for partial failure between these operations.

### Suggested flow

1.  Client sends a task submission request.
2.  API validates the request and idempotency key.
3.  PostgreSQL transaction inserts the task and idempotency record.
4.  The system schedules or signals the task for processing.
5.  Worker claims the task using a safe database operation or lease.
6.  Worker executes a registered handler.
7.  Worker records success, retryable failure, permanent failure, or
    cancellation.
8.  Metrics and structured logs record the outcome.
9.  Recovery logic identifies expired leases and safely resumes eligible
    work.

------------------------------------------------------------------------

## 6. Data Model

Use PostgreSQL migrations. Names below are logical schema suggestions;
choose consistent SQL naming conventions and document them.

### `tasks`

  -----------------------------------------------------------------------
  Field                               Purpose
  ----------------------------------- -----------------------------------
  `id`                                UUID primary key

  `task_type`                         Registered handler name

  `payload`                           Validated JSON payload

  `status`                            queued, running, succeeded, failed,
                                      cancelled, dead_letter

  `priority`                          Optional bounded priority

  `attempt_count`                     Number of attempts made

  `max_attempts`                      Maximum permitted attempts

  `created_at`                        Creation timestamp

  `scheduled_at`                      Earliest eligible processing time

  `started_at`                        Current or most recent start time

  `completed_at`                      Terminal completion time

  `updated_at`                        Last state update

  `result`                            Safe JSON result or summary

  `last_error_code`                   Sanitized error classification

  `last_error_message`                Sanitized error description

  `lease_owner`                       Current worker identity, if leased

  `lease_expires_at`                  Lease expiry time

  `correlation_id`                    Traceable request or task
                                      correlation identifier
  -----------------------------------------------------------------------

### `task_attempts`

Store one record for each attempt:

-   Attempt ID.
-   Task ID.
-   Attempt number.
-   Worker ID.
-   Start and end timestamps.
-   Outcome.
-   Sanitized error code and message.
-   Execution duration.
-   Optional retry delay.

### `idempotency_records`

-   Scope or client identifier.
-   Idempotency key.
-   Request fingerprint.
-   Original task ID.
-   Creation and expiration timestamps if expiry is supported.

Create a unique constraint over the chosen scope and idempotency key.

### `dead_letter_tasks`

This may be a separate table or a documented terminal state with
retained attempt history. Prefer a design that keeps the original task
and its history inspectable. Document how an operator can requeue a task
without losing audit history.

### Indexes

Evaluate indexes for:

-   Task status and scheduled time.
-   Creation time and ID for stable listing.
-   Lease expiry for recovery.
-   Task type and status where query patterns justify it.
-   Idempotency scope and key with a uniqueness constraint.

Do not add indexes blindly. Explain the query each index supports.

------------------------------------------------------------------------

## 7. API Contract

Version the API under `/api/v1`.

### Endpoints

  -----------------------------------------------------------------------------------------
  Method                  Endpoint                                  Purpose
  ----------------------- ----------------------------------------- -----------------------
  `POST`                  `/api/v1/tasks`                           Submit a task

  `GET`                   `/api/v1/tasks/{taskId}`                  Get task status

  `GET`                   `/api/v1/tasks`                           List tasks with filters
                                                                    and pagination

  `POST`                  `/api/v1/tasks/{taskId}/cancel`           Request cancellation

  `GET`                   `/api/v1/dead-letters`                    Inspect dead letter
                                                                    tasks

  `POST`                  `/api/v1/dead-letters/{taskId}/requeue`   Requeue an eligible
                                                                    dead letter task

  `GET`                   `/health/live`                            Process liveness

  `GET`                   `/health/ready`                           Dependency readiness

  `GET`                   `/metrics`                                Prometheus metrics
  -----------------------------------------------------------------------------------------

Administrative endpoints must be protected or bound to local development
use only until authentication and authorization are implemented.

### Example submission request

``` json
{
  "taskType": "generateReport",
  "payload": {
    "reportName": "weekly-performance",
    "periodDays": 7
  },
  "maxAttempts": 4
}
```

Use the `Idempotency-Key` request header for duplicate protection.

### Example successful response

``` json
{
  "taskId": "generated-uuid",
  "status": "queued",
  "statusUrl": "/api/v1/tasks/generated-uuid"
}
```

This is a contract example. The UUID must be generated at runtime.

### Error conventions

Use consistent HTTP status codes and structured error bodies. Cover
malformed JSON, schema validation failure, unsupported task types,
conflicting idempotency keys, missing tasks, unauthorized administrative
requests, and dependency unavailability.

Never return raw stack traces to clients.

------------------------------------------------------------------------

## 8. Task State Machine

Document and enforce transitions.

  -----------------------------------------------------------------------
  Current state           Event                   Next state
  ----------------------- ----------------------- -----------------------
  queued                  Worker claims task      running

  queued                  Cancellation accepted   cancelled

  running                 Handler succeeds        succeeded

  running                 Retryable failure with  queued, scheduled for
                          attempts remaining      later

  running                 Permanent failure       failed

  running                 Retry limit exhausted   dead_letter

  running                 Lease expires           Recovery process
                                                  evaluates and requeues
                                                  safely

  dead_letter             Authorized requeue      queued

  succeeded               Any ordinary transition Not allowed

  cancelled               Any ordinary transition Not allowed
  -----------------------------------------------------------------------

Define whether a cancelled task can be requeued. Prefer a deliberate
administrative operation rather than an implicit transition. Write unit
tests for every allowed and rejected transition.

------------------------------------------------------------------------

## 9. Repository Structure

Start with a clean, modular layout. Adjust names if the selected
libraries require it, but preserve separation of responsibilities.

``` text
pulsequeue/
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── migrations/
├── src/
│   └── pulsequeue/
│       ├── __init__.py
│       ├── main.py
│       ├── api/
│       │   ├── routes/
│       │   ├── schemas.py
│       │   └── errorHandlers.py
│       ├── core/
│       │   ├── config.py
│       │   ├── loggingConfig.py
│       │   └── security.py
│       ├── domain/
│       │   ├── models.py
│       │   ├── stateMachine.py
│       │   ├── retryPolicy.py
│       │   └── errors.py
│       ├── persistence/
│       │   ├── database.py
│       │   ├── repositories.py
│       │   └── models.py
│       ├── queueing/
│       │   ├── redisQueue.py
│       │   └── dispatcher.py
│       ├── workers/
│       │   ├── worker.py
│       │   ├── registry.py
│       │   └── handlers.py
│       ├── recovery/
│       │   └── leaseRecovery.py
│       └── observability/
│           ├── metrics.py
│           └── health.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── concurrency/
│   ├── recovery/
│   └── performance/
├── scripts/
│   ├── seedDemoData.py
│   └── runBenchmark.py
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── operationsRunbook.md
│   ├── threatModel.md
│   └── decisions/
└── benchmarks/
    ├── README.md
    └── results/
```

Do not create empty files solely to imitate this structure. Add modules
as their responsibilities are implemented. Use camelCase for Python
function names, as required by the project's style preference, while
following standard conventions for third party interfaces and generated
code where necessary.

------------------------------------------------------------------------

# Implementation Phases

## Phase 0: Repository audit and engineering plan

**Duration:** Half day to one day.

### Tasks

1.  Create a new GitHub repository named `PulseQueue`.
2.  Add a project description focused on reliable distributed task
    processing.
3.  Create the initial README with project goals, architecture outline,
    scope, and status.
4.  Choose Python version and pin supported dependency ranges.
5.  Decide on SQLAlchemy, Alembic, Pydantic, FastAPI, Redis client,
    pytest, HTTPX, Ruff, and a type checker.
6.  Decide whether workers use a custom loop or an established task
    execution abstraction. Prefer a small, understandable implementation
    that makes failure handling visible.
7.  Write architecture decision records for:
    -   PostgreSQL as source of truth.
    -   Redis role and recovery strategy.
    -   Worker claim and lease design.
    -   Retry and idempotency semantics.
8.  Add `.gitignore`, `.env.example`, and a license if appropriate.
9.  Define acceptance criteria before coding.

### Deliverables

-   Repository skeleton.
-   Project charter.
-   Initial architecture diagram.
-   Decision records.
-   Reproducible development setup.

### Exit criteria

A reviewer can understand what the project does, what it intentionally
does not do, and how its components will interact.

## Phase 1: API and domain model

**Duration:** 3 to 4 days.

### Tasks

1.  Configure FastAPI and application startup and shutdown.
2.  Implement typed request and response schemas.
3.  Define task types and allowed payload schemas.
4.  Implement domain models and the state machine.
5.  Create structured error responses.
6.  Add task submission and retrieval endpoints.
7.  Add stable task identifiers and timestamps.
8.  Configure PostgreSQL access and migrations.
9.  Implement task repository methods.
10. Add unit tests for validation, state transitions, and error cases.
11. Add API integration tests against a test database.

### Tests

-   Valid task submission.
-   Missing task type.
-   Unsupported task type.
-   Invalid payload.
-   Payload too large.
-   Unknown task ID.
-   Invalid state transition.
-   Database unavailable.
-   Migration from an empty database.

### Exit criteria

The API persists valid tasks and returns predictable errors. No worker
or Redis integration is required yet.

## Phase 2: Queue and worker execution

**Duration:** 4 to 5 days.

### Tasks

1.  Add Redis through Docker Compose.
2.  Implement the queue adapter.
3.  Implement a worker process separate from the API.
4.  Add a registry of permitted task handlers.
5.  Implement task claiming using a safe database transaction or lease.
6.  Ensure workers cannot concurrently claim the same task.
7.  Implement success and failure persistence.
8.  Store attempt history.
9.  Add graceful worker shutdown.
10. Add structured logs with task and worker identifiers.
11. Add integration tests with real PostgreSQL and Redis services.

### Important design requirement

Do not rely solely on an in memory queue or a Redis enqueue operation as
proof that a task is durably accepted. A database commit followed by a
failed Redis publish creates a partial failure. Implement a recovery
mechanism or transactional outbox pattern so the task can still be
discovered and processed.

### Exit criteria

Tasks submitted through the API can be executed by separate workers, and
results and failures remain visible after process restarts.

## Phase 3: Retries, idempotency, and recovery

**Duration:** 4 to 5 days.

### Tasks

1.  Implement configurable maximum attempts.
2.  Implement exponential backoff with jitter and bounded maximum delay.
3.  Distinguish retryable errors from permanent failures.
4.  Implement idempotency key storage and uniqueness constraints.
5.  Calculate a stable request fingerprint.
6.  Return the original task for duplicate equivalent requests.
7.  Return a conflict when a key is reused for a different request.
8.  Implement worker leases or heartbeats.
9.  Implement lease expiry recovery.
10. Implement dead letter inspection and controlled requeue.
11. Preserve attempt history during recovery and requeue.
12. Test crashes at different points in the task lifecycle.

### Fault scenarios

-   Worker crashes before starting a task.
-   Worker crashes during execution.
-   Worker finishes work but fails before recording completion.
-   Redis becomes unavailable after the task is committed.
-   PostgreSQL temporarily becomes unavailable.
-   Multiple clients submit the same idempotency key simultaneously.
-   A task fails until the retry limit is reached.
-   A worker lease expires while a worker is still alive.

### Critical correctness consideration

A worker may execute a side effect and crash before recording success.
The task could run again after recovery. Design handlers to be
idempotent where possible, use idempotency keys for external operations
if available, and document that queue level deduplication does not
guarantee exactly once external side effects.

### Exit criteria

The documented retry and recovery guarantees are backed by automated
tests.

## Phase 4: Pagination, filtering, cancellation, and API quality

**Duration:** 2 to 3 days.

### Tasks

1.  Add task listing with stable pagination.
2.  Add filters for task status and type.
3.  Add a maximum page size.
4.  Add database indexes based on actual queries.
5.  Implement safe cancellation semantics.
6.  Add request correlation IDs.
7.  Add rate limiting if appropriate for the local deployment model.
8.  Review all API response codes and error messages.
9.  Add API examples and schema documentation.

### Exit criteria

The API remains predictable for large result sets and concurrent
clients. Cancellation behavior is documented and tested.

## Phase 5: Automated tests and continuous integration

**Duration:** 3 to 4 days, overlapping with previous phases.

### Testing layers

**Unit tests** - State machine. - Retry calculation. - Request
fingerprinting. - Idempotency decisions. - Error classification. -
Handler input validation.

**Integration tests** - API with PostgreSQL. - API and workers with
Redis. - Persistence and retry scheduling. - Dead letter requeue. -
Migration validation.

**Concurrency tests** - Multiple workers claim tasks at the same time. -
Concurrent duplicate submissions. - High volume task listing. -
Simultaneous task cancellation and claim attempts.

**Recovery tests** - Kill a worker process during a task. - Restart
dependencies. - Simulate a lost queue notification. - Verify lease
expiry recovery. - Verify task history remains consistent.

### CI pipeline

Configure GitHub Actions to run:

1.  Dependency installation.
2.  Ruff linting and formatting checks.
3.  Static type checking.
4.  Unit tests.
5.  Integration tests with service containers.
6.  Coverage reporting.
7.  Build validation.

Use a coverage threshold only after the test suite is meaningful.
Coverage percentage is not a substitute for assertions about
correctness.

### Exit criteria

A clean checkout can run the documented test suite, and CI reliably
detects regressions.

## Phase 6: Observability and operations

**Duration:** 3 to 4 days.

### Tasks

1.  Implement liveness and readiness endpoints.
2.  Add Prometheus metrics.
3.  Record task counts by bounded state labels.
4.  Measure execution duration and queue wait duration.
5.  Measure API request latency and error counts.
6.  Add worker heartbeats.
7.  Configure Grafana dashboards.
8.  Add alerts or documented alert thresholds for queue growth, high
    failure rates, and unavailable workers.
9.  Add log correlation IDs.
10. Write an operations runbook.

### Required metrics

-   `pulsequeueTasksSubmittedTotal`
-   `pulsequeueTasksCompletedTotal`
-   `pulsequeueTasksFailedTotal`
-   `pulsequeueTasksRetriedTotal`
-   `pulsequeueQueueDepth`
-   `pulsequeueTaskExecutionSeconds`
-   `pulsequeueTaskQueueWaitSeconds`
-   `pulsequeueWorkerHeartbeatAgeSeconds`
-   `pulsequeueApiRequestsTotal`
-   `pulsequeueApiRequestDurationSeconds`

Use metric naming conventions appropriate to the selected Prometheus
client. Keep labels low cardinality. Never attach task IDs or arbitrary
user supplied values as metric labels.

### Exit criteria

A reviewer can identify whether the system is healthy, whether tasks are
accumulating, and where failures or latency are occurring.

## Phase 7: Performance testing and optimization

**Duration:** 3 to 4 days.

### Test plan

1.  Define a repeatable workload with a fixed mix of task types and
    payload sizes.
2.  Record hardware, operating system, Python version, dependency
    versions, Docker configuration, and database settings.
3.  Run a warm up phase.
4.  Test one worker and multiple workers.
5.  Increase client concurrency gradually.
6.  Measure accepted tasks per second, completed tasks per second, p50
    and p95 latency, queue wait time, failure rate, and resource
    consumption.
7.  Identify bottlenecks using metrics and profiling.
8.  Make one targeted optimization at a time.
9.  Rerun the same workload.
10. Store the raw results and compare baseline with optimized results.

### Rules for credible benchmarks

-   Do not invent throughput numbers.
-   Do not compare runs with different workloads without explaining the
    difference.
-   Report both successful throughput and error rate.
-   State whether measurements include queue waiting or only handler
    execution.
-   Document the test environment and limitations.
-   Do not claim production scale from local Docker measurements.

### Exit criteria

The repository contains reproducible benchmark instructions, measured
results, and an evidence based explanation of at least one bottleneck or
tradeoff.

## Phase 8: Security and hardening

**Duration:** 2 to 3 days.

### Tasks

1.  Validate payload schemas and size limits.
2.  Add authentication and authorization before exposing administrative
    operations.
3.  Protect requeue and cancellation operations.
4.  Keep secrets outside source control.
5.  Sanitize errors and logs.
6.  Restrict task handlers to an explicit allowlist.
7.  Prevent path traversal in file processing handlers.
8.  Set connection, request, and task execution timeouts.
9.  Review dependency vulnerabilities.
10. Add a basic threat model.
11. Test unauthorized administrative requests.
12. Document known risks and mitigations.

### Exit criteria

The application has a documented security boundary and does not expose
unsafe task execution or administrative controls by default.

## Phase 9: Packaging, documentation, and portfolio presentation

**Duration:** 2 to 3 days.

### Tasks

1.  Finish Docker Compose configuration.
2.  Add a one command or clearly documented startup workflow.
3.  Document environment variables and migrations.
4.  Add an architecture diagram.
5.  Document task lifecycle and delivery guarantees.
6.  Document API endpoints and examples.
7.  Add a failure recovery walkthrough.
8.  Add a benchmark report with real measurements.
9.  Add test and CI badges only if they are accurate.
10. Add screenshots of dashboards only if the dashboards exist.
11. Record a short demo showing task submission, execution, retry, and
    monitoring.
12. Add limitations and future work.
13. Review the README from the perspective of a recruiter who has never
    seen the project.

### Final acceptance checklist

-   [ ] New developer can run the project from the README.
-   [ ] Database migrations work from a clean state.
-   [ ] API validates requests and returns consistent errors.
-   [ ] Workers execute tasks independently from the API.
-   [ ] Duplicate submissions are handled correctly.
-   [ ] Retries are bounded and scheduled correctly.
-   [ ] Dead letter tasks can be inspected.
-   [ ] Worker failure recovery is tested.
-   [ ] Task state transitions are enforced.
-   [ ] Unit, integration, concurrency, and recovery tests exist.
-   [ ] CI runs tests and quality checks.
-   [ ] Metrics and structured logs are available.
-   [ ] Benchmark methodology and results are documented.
-   [ ] Security limitations are documented.
-   [ ] No secrets, real customer data, or invented results are
    committed.
-   [ ] Resume claims match the implemented code and measured evidence.

------------------------------------------------------------------------

# Engineering Design Details

## Retry strategy

Use a bounded exponential delay such as:

`delay = min(maxDelay, baseDelay * 2 ** (attemptNumber - 1))`

Add randomized jitter to the computed delay. Validate configuration
values and avoid integer overflow or unbounded waits. Tests should use a
controllable clock or inject the delay calculator rather than sleeping
for long periods.

## Worker claim and lease strategy

A worker must atomically claim an eligible task. Evaluate PostgreSQL row
locking and `SKIP LOCKED` or an equivalent transaction based claim
mechanism. A lease should include owner and expiration fields. Updates
should verify the current lease owner so a stale worker cannot overwrite
a newer worker's state.

A lease does not magically prevent an old worker from completing a side
effect after its lease expires. Use ownership checks, safe handler
design, and documented limitations.

## Transactional outbox or recovery

The simplest robust design may use a PostgreSQL backed outbox or a
periodic poller that discovers eligible queued tasks. If an outbox is
used:

1.  Insert the task and outbox event in the same database transaction.
2.  A dispatcher publishes pending events to Redis.
3.  Mark events published only after successful publication.
4.  Make repeated publication harmless.
5.  Retain a recovery path for lost or duplicated messages.

Choose one approach, explain the tradeoffs, and test partial failures.

## Database migrations

Use Alembic or an equivalent migration tool. Do not rely on automatic
table creation as the only schema management strategy. Test upgrades
from an empty database and document how developers reset their local
environment.

## Error classification

Use explicit error categories:

-   Validation error: permanent, do not retry.
-   Unsupported task type: permanent, do not retry.
-   Temporary database or network error: potentially retryable.
-   Handler business rule violation: usually permanent unless explicitly
    defined otherwise.
-   Worker process crash: recover through lease expiry and attempt
    policy.
-   Retry exhaustion: move to dead letter state.

Do not retry every exception indiscriminately.

## Cancellation

Cancellation is straightforward before a task starts. For a running
task, cancellation should be cooperative. A handler may periodically
check a cancellation signal or use a cancellation token. If a handler
cannot safely stop, record the request and communicate the actual state
rather than claiming it stopped immediately.

------------------------------------------------------------------------

# Suggested Definition of Done

A phase is complete only when:

1.  Its implementation exists in the repository.
2.  The relevant tests pass.
3.  Errors and edge cases are considered.
4.  Documentation matches the actual behavior.
5.  Code is reviewed for duplication, naming, and unnecessary
    complexity.
6.  The feature is committed in a focused Git commit.
7.  Any known limitation is written down.

Avoid implementing all phases in one giant change. Small, reviewable
commits create better engineering evidence and make failures easier to
diagnose.

------------------------------------------------------------------------

# Git Workflow

Use a branch based workflow:

-   `main`: always runnable and tested.
-   `feature/task-api`: API and domain work.
-   `feature/worker-execution`: queue and worker work.
-   `feature/retry-recovery`: retry and recovery work.
-   `feature/observability`: metrics and health checks.
-   `feature/benchmarking`: load tests and benchmark reports.

Use descriptive commit messages, for example:

-   `Add task submission and retrieval endpoints`
-   `Implement atomic worker task claiming`
-   `Add bounded retry scheduling`
-   `Test idempotent concurrent submissions`
-   `Expose queue depth and worker health metrics`

Do not commit generated secrets, local database volumes, virtual
environments, or unreviewed benchmark output.

------------------------------------------------------------------------

# Claude Code Implementation Prompt

Copy the prompt below into Claude Code from the root of your
`PulseQueue` repository. It is designed to make Claude Code work
incrementally, inspect its own changes, and avoid pretending that
unfinished work is complete.

## Prompt begins

You are the senior software engineer and technical mentor responsible
for implementing PulseQueue, a portfolio grade distributed task
processing and reliability platform. Work directly in the current
repository.

### 1. Mission

Build a robust, understandable, well tested task processing system using
Python, FastAPI, PostgreSQL, Redis, Docker Compose, pytest, and GitHub
Actions.

The purpose is to demonstrate software engineering skills relevant to an
entry level software engineering role: modular design, API development,
data modeling, concurrency, error handling, testing, reliability,
observability, performance measurement, documentation, and sound
engineering tradeoffs.

This is a real implementation task. Do not merely write a plan or
generate placeholder files. Inspect the repository, implement working
features, execute tests where possible, and report actual results.

### 2. Operating rules

1.  Begin by inspecting the current repository, existing files, Git
    status, Python version, dependencies, and available tests.
2.  Do not delete or overwrite existing user work without first
    understanding it.
3.  If the repository is empty, create a clean project structure.
4.  Before coding, write a short implementation plan and list important
    design decisions.
5.  Implement one phase at a time. Do not attempt the entire project in
    one giant patch.
6.  After each phase, run the relevant tests, linting, formatting
    checks, and type checks available in the environment.
7.  Fix failures caused by your changes before continuing.
8.  Never claim that a test passed unless you actually ran it and
    observed a successful result.
9.  Never invent benchmark results, test coverage, performance
    improvements, deployment status, or security guarantees.
10. If Docker, Redis, PostgreSQL, or another dependency is unavailable,
    state the limitation, run all checks that remain possible, and
    provide the exact command needed for the blocked check.
11. Ask for clarification only when an important decision cannot
    reasonably be made from this specification. Otherwise choose a
    sensible default and document it.
12. Do not deploy to paid cloud services, publish secrets, or perform
    destructive actions without explicit approval.
13. Keep `main` runnable. Do not change branches or make Git commits
    unless asked.
14. Prefer small, reviewable changes with a clear reason for each.
15. At the end of each work session, summarize files changed, decisions
    made, commands run, results, limitations, and the next phase.

### 3. Code quality and style

-   Use type hints on public functions and meaningful internal
    interfaces.
-   Use clear, focused modules and avoid monolithic files.
-   Use Python exceptions deliberately. Do not swallow errors.
-   Validate all external input at the API boundary.
-   Separate HTTP concerns from domain logic and persistence.
-   Use dependency injection where it improves testing without adding
    unnecessary complexity.
-   Use parameterized database operations and safe transaction
    boundaries.
-   Use timezone aware UTC timestamps.
-   Make state transitions explicit.
-   Use camelCase for Python function names in this project, following
    the repository owner's preference. Use clear class names,
    descriptive variables, and conventional names required by frameworks
    or third party interfaces when necessary.
-   Use constants or validated configuration for tunable values.
-   Avoid unnecessary abstractions and excessive dependencies.
-   Never hardcode secrets.
-   Do not execute arbitrary code or shell commands from task payloads.
-   Do not return raw exception stack traces through the API.
-   Do not add an abstraction solely to make the architecture look
    sophisticated.

### 4. Architecture requirements

Implement these logical components:

1.  FastAPI application and versioned API.
2.  Domain models, task state machine, retry policy, and domain errors.
3.  PostgreSQL persistence with migrations.
4.  Redis backed queue signaling or dispatch.
5.  Separate worker process.
6.  Registered and allowlisted task handlers.
7.  Retry scheduling and dead letter handling.
8.  Idempotency key storage and request fingerprinting.
9.  Worker lease or heartbeat management.
10. Recovery for expired leases and lost queue notifications.
11. Structured logging, health checks, and Prometheus metrics.
12. Automated unit, integration, concurrency, and recovery tests.
13. Load testing and reproducible benchmark instructions.
14. Docker Compose and GitHub Actions.
15. Architecture documentation, API documentation, an operations
    runbook, and a threat model.

PostgreSQL is the source of truth for task state. Redis may be used for
dispatch and coordination, but accepted tasks must remain recoverable if
Redis loses messages or restarts.

Explicitly address partial failure between committing a task to
PostgreSQL and publishing a Redis message. Choose and document a
transactional outbox or a reliable database polling and recovery
approach. Do not assume these two operations are atomic.

### 5. Required task behavior

Implement the following task states:

-   `queued`
-   `running`
-   `succeeded`
-   `failed`
-   `cancelled`
-   `dead_letter`

Define and enforce allowed transitions. Reject invalid transitions. Keep
attempt history for debugging and auditability.

The API must support:

-   `POST /api/v1/tasks`
-   `GET /api/v1/tasks/{taskId}`
-   `GET /api/v1/tasks`
-   `POST /api/v1/tasks/{taskId}/cancel`
-   `GET /api/v1/dead-letters`
-   `POST /api/v1/dead-letters/{taskId}/requeue`
-   `GET /health/live`
-   `GET /health/ready`
-   `GET /metrics`

Use consistent validation and error response formats. Add stable
pagination, a maximum page size, and appropriate database indexes.

### 6. Idempotency and concurrency

Support the `Idempotency-Key` header on task submission.

-   Store the key and a stable fingerprint of the logical request.
-   Return the original task when the same key is reused for an
    equivalent request.
-   Return a conflict when the same key is reused with a different
    request.
-   Enforce uniqueness in PostgreSQL so concurrent requests cannot
    create duplicate logical tasks.
-   Add concurrency tests that submit duplicate requests simultaneously.
-   Atomically claim tasks so two workers cannot own the same task at
    once.
-   Use leases or equivalent ownership tracking to recover abandoned
    work.
-   Ensure stale workers cannot overwrite state owned by a newer worker.
-   Document the limitation that a crash after a side effect but before
    recording success may cause that side effect to happen again.
-   Do not claim exactly once execution.

Use idempotent task handlers wherever practical.

### 7. Retry and failure policy

Implement:

-   Configurable maximum attempts.
-   Exponential backoff with bounded maximum delay.
-   Randomized jitter.
-   Retryable versus permanent error classification.
-   Persistent attempt history.
-   Dead letter handling after retry exhaustion.
-   Controlled administrative requeue.
-   Lease expiry recovery.
-   Graceful worker shutdown.

Do not retry validation failures or unsupported task types indefinitely.
Do not retry every exception indiscriminately. Make timing calculations
unit testable without long sleeps by injecting a clock or testing the
retry calculation separately.

### 8. Demo handlers

Implement only safe, deterministic handlers, such as:

-   `generateReport`
-   `calculateMetrics`
-   `processFile` for a controlled test directory and strictly validated
    inputs
-   `sendNotification` as a simulated notification, not a real external
    send
-   `simulateFailure` only in development and testing, with explicit
    controls

Never use `eval`, arbitrary Python execution, unrestricted shell
execution, or arbitrary user supplied filesystem paths.

Example demo names can include Sachin Yadav, Hema C, Arjun Ramesh,
Shaurya Mishra, and Shubham Kundu. Treat these as sample data only, not
actual customer identities.

### 9. Data model

At minimum, persist:

**Tasks:** UUID, type, JSON payload, state, priority if implemented,
attempt count, max attempts, creation time, scheduled time, start time,
completion time, update time, result, sanitized last error, worker lease
owner, lease expiry, and correlation ID.

**Task attempts:** task ID, attempt number, worker ID, start and end
timestamps, outcome, sanitized error details, and duration.

**Idempotency records:** key scope, idempotency key, request
fingerprint, original task ID, and timestamps.

Use Alembic or an equivalent migration tool. Include indexes justified
by real query patterns. Do not rely solely on automatic table creation.

### 10. Observability

Implement structured JSON logs with task IDs, worker IDs, and
correlation IDs.

Expose metrics for:

-   Submitted, completed, failed, retried, and dead letter tasks.
-   Queue depth by state.
-   Task execution duration.
-   Queue wait duration.
-   Worker heartbeat age.
-   API request count, duration, and errors.

Use low cardinality metric labels. Never use task IDs, raw payloads, or
idempotency keys as metric labels.

Add liveness and readiness checks. Document how to use Prometheus and
Grafana, and include dashboard configuration only when it works.

### 11. Testing requirements

Use pytest and HTTPX as appropriate.

Write tests for:

**Unit behavior** - Input validation. - State transitions. - Retry
calculation and error classification. - Idempotency fingerprints. - Task
handler registration. - Cancellation rules.

**Integration behavior** - Task creation and retrieval. - Database
migrations. - Worker processing. - Retry scheduling. - Dead letter
handling. - Administrative requeue. - API error responses.

**Concurrency** - Concurrent worker claims. - Concurrent duplicate
submissions. - Cancellation racing with task claim. - Pagination while
new tasks are being created.

**Recovery and fault injection** - Worker killed during execution. -
Expired lease recovery. - Redis unavailable after task persistence. -
Lost or duplicate queue notification. - Database connection failure. -
Retry exhaustion. - Restart with queued and running tasks.

Do not make tests flaky through arbitrary sleeps. Use deterministic
synchronization primitives, controlled clocks, bounded polling, and
isolated test data.

### 12. CI and quality checks

Configure GitHub Actions to run:

1.  Dependency installation.
2.  Ruff lint checks.
3.  Formatting checks.
4.  Static type checking.
5.  Unit tests.
6.  Integration tests with PostgreSQL and Redis services.
7.  Coverage reporting.
8.  Application build or import validation.

Do not invent coverage percentages. Add a coverage threshold only when
justified by a meaningful test suite.

### 13. Benchmarking

Use Locust or another appropriate load testing tool.

Provide a repeatable benchmark command and capture:

-   Workload mix.
-   Client concurrency.
-   Worker count.
-   Task submission rate.
-   Completed tasks per second.
-   p50 and p95 latency.
-   Queue wait time.
-   Error rate.
-   CPU and memory where measurable.
-   Python, operating system, Docker, database, and Redis configuration.

Compare one worker with multiple workers. Profile the application and
explain at least one real bottleneck or tradeoff. Do not optimize
blindly. Do not claim results until the benchmark has actually run.

Store results with the exact configuration and commands needed to
reproduce them. Separate committed benchmark instructions from
environment specific result files.

### 14. Security requirements

-   Validate request schemas and payload size.
-   Use environment based configuration.
-   Include `.env.example` without real secrets.
-   Protect administrative operations.
-   Do not expose administrative endpoints publicly without
    authentication and authorization.
-   Sanitize errors and logs.
-   Restrict handlers to an explicit registry.
-   Restrict file processing to a controlled directory.
-   Set timeouts and sensible connection limits.
-   Document the threat model and known limitations.
-   Do not claim a professional security audit.

### 15. Documentation requirements

Maintain:

-   `README.md`
-   `docs/architecture.md`
-   `docs/api.md`
-   `docs/operationsRunbook.md`
-   `docs/threatModel.md`
-   `docs/decisions/` for architecture decision records
-   Benchmark methodology and real results when available

The README must contain project purpose, architecture, technology stack,
prerequisites, setup, environment variables, migrations, startup, test
commands, API examples, monitoring instructions, benchmark instructions,
limitations, and current implementation status.

Use portable paths and commands. Do not include machine specific paths.

### 16. Required implementation order

Work in this order and do not skip ahead without explaining why:

**Phase 0:** Inspect repository, establish architecture, write decision
records and acceptance criteria.

**Phase 1:** API, domain model, PostgreSQL persistence, migrations, unit
and integration tests.

**Phase 2:** Redis integration, worker execution, task claiming, attempt
records, structured logs.

**Phase 3:** Idempotency, bounded retries, leases, dead letter handling,
and recovery.

**Phase 4:** Pagination, filtering, cancellation, and API quality.

**Phase 5:** Comprehensive tests and GitHub Actions.

**Phase 6:** Health checks, metrics, logs, and monitoring.

**Phase 7:** Load testing, profiling, benchmarks, and evidence based
optimization.

**Phase 8:** Security hardening and threat model.

**Phase 9:** Packaging, documentation, demo workflow, and final review.

At the end of each phase:

1.  List the implemented behavior.
2.  List files created or changed.
3.  Run tests and quality checks.
4.  Report exact commands and their actual outcomes.
5.  Identify unresolved issues and technical debt.
6.  Update the README and implementation checklist.
7.  Stop and wait for review before making a large architectural change.

### 17. First task

Start with Phase 0 only.

Inspect the repository and environment. Produce a concise implementation
plan, identify risks, and create the initial project documentation and
architecture decision records. Do not implement the entire application
in the first response. After Phase 0 is complete, report what you
actually inspected and changed, then propose the first small
implementation increment.

The project is successful only when the code, tests, documentation, and
measured results support the claims being made. Maintain that standard
throughout.

## Prompt ends

------------------------------------------------------------------------

# How to use this specification effectively

1.  Create the GitHub repository and open its root folder in Claude
    Code.
2.  Save this specification as `PROJECT_PLAN.md` in the repository.
3.  Paste the Claude Code prompt into the Claude Code session.
4.  Review Phase 0 before approving implementation.
5.  Require tests and a short explanation of each architectural decision
    at every phase.
6.  Run the project locally yourself and understand the code well enough
    to explain the design, failures, and tradeoffs in an interview.
7.  Keep the project status honest. Mark features as planned,
    implemented, or verified rather than presenting the entire roadmap
    as completed.

The best portfolio evidence will be the repository history, passing
tests, reproducible failure recovery, and benchmark results, not the
length of the specification.
