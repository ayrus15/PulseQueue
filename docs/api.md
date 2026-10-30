# API documentation

**Status: Phase 4 — task submission/retrieval/listing/cancellation and
dead-letter administration all exist.** `/health/*` / `/metrics` are
Phase 6. Examples below are drawn directly from the integration tests,
not hand-written.

All endpoints are under `/api/v1`. Every response, success or error,
carries an `X-Correlation-Id` header (the client's own, if it sent a
sane one via that same header; otherwise a generated UUID - see
`api/middleware.py`). Errors always have the shape:

```json
{"error": {"code": "TaskNotFoundError", "message": "Task not found: ..."}}
```

`code` is the raising exception's class name for domain errors
(`UnsupportedTaskTypeError`, `TaskNotFoundError`, `IdempotencyConflictError`,
`UnauthorizedError`, `RateLimitExceededError`, ...), or
`RequestValidationError` / `ValidationError` for malformed requests,
unknown filter values, or payloads that fail their task type's schema,
or `InternalServerError` for anything unexpected (never a raw stack trace).

## `POST /api/v1/tasks`

Request:

```json
{
  "taskType": "generateReport",
  "payload": { "reportName": "weekly-performance", "periodDays": 7 },
  "maxAttempts": 3
}
```

`maxAttempts` is optional (defaults to `PULSEQUEUE_DEFAULT_MAX_ATTEMPTS`,
currently 4). `payload` must match the schema registered for `taskType`
in `src/pulsequeue/domain/taskTypes.py`; see that module for all five
registered types (`generateReport`, `calculateMetrics`, `processFile`,
`sendNotification`, `simulateFailure`) and their fields.

An optional `Idempotency-Key` header (any client-chosen string) makes
retries safe (ADR 0004):

- First use of a key → `201 Created`, as above.
- Same key + the same `taskType`/`payload`/`maxAttempts` → `200 OK`
  with the *original* task (no new task created).
- Same key + a different request → `409 Conflict`, `IdempotencyConflictError`.

An optional `X-Correlation-Id` header becomes the created task's
`correlationId` (see `GET /api/v1/tasks/{taskId}` below) - useful for
tracing a task back to the request and logs that created it.

If `PULSEQUEUE_RATE_LIMIT_ENABLED=true` (off by default - see
`api/rateLimit.py`), exceeding `PULSEQUEUE_RATE_LIMIT_PER_MINUTE`
requests per client IP returns `429`, `RateLimitExceededError`.

Response (`201 Created`, or `200 OK` for a repeated idempotency key):

```json
{
  "taskId": "b3f1...-uuid",
  "status": "queued",
  "statusUrl": "/api/v1/tasks/b3f1...-uuid"
}
```

Failure modes exercised by tests:

- Unknown `taskType` → `400`, `UnsupportedTaskTypeError`.
- `payload` doesn't match the registered schema for `taskType` → `422`.
- Missing/malformed request body (e.g. no `taskType` at all) → `422`,
  `RequestValidationError`.
- `payload` serializes to more than 32 KiB → `422`.
- Idempotency key reused with a different request → `409`.
- Rate limit exceeded (only if enabled) → `429`.

## `GET /api/v1/tasks`

Query parameters, all optional:

| Parameter | Meaning |
|---|---|
| `limit` | Max results (default 50, max 100) |
| `status` | One of `queued`/`running`/`succeeded`/`failed`/`cancelled`/`dead_letter` |
| `taskType` | One of the five registered task types |
| `cursor` | Opaque value from a previous response's `nextCursor` |

```json
{"tasks": [ /* TaskDetailResponse objects, see below */ ], "nextCursor": "b64-opaque-string-or-null"}
```

Ordered by `(createdAt, id)` ascending - deterministic and stable: new
inserts never shift a page already handed out (FR3). Pass `nextCursor`
back as `cursor` to get the next page; `null` means there isn't one.
An unknown `status`/`taskType` value or a malformed `cursor` → `422`.

## `GET /api/v1/tasks/{taskId}`

Response (`200 OK`):

```json
{
  "taskId": "b3f1...-uuid",
  "taskType": "generateReport",
  "status": "succeeded",
  "attemptCount": 1,
  "maxAttempts": 4,
  "createdAt": "2026-10-29T12:00:00+00:00",
  "scheduledAt": "2026-10-29T12:00:00+00:00",
  "startedAt": "2026-10-29T12:00:01+00:00",
  "completedAt": "2026-10-29T12:00:01+00:00",
  "updatedAt": "2026-10-29T12:00:01+00:00",
  "result": {"reportName": "weekly-performance", "summary": "..."},
  "lastErrorCode": null,
  "lastErrorMessage": null,
  "correlationId": "c9a2...-uuid"
}
```

- Unknown or malformed `taskId` → `404` (`TaskNotFoundError`) if it's a
  valid UUID that doesn't exist, `422` if it isn't a valid UUID at all.
- `status` can be any of `queued`, `running`, `succeeded`, `failed`,
  `cancelled`, `dead_letter`.

## `POST /api/v1/tasks/{taskId}/cancel`

Cancels a task that hasn't started yet. Response (`200 OK`): the
task's `TaskDetailResponse`, with `status: "cancelled"`.

- A task that's already `running` or otherwise past `queued` → `409`,
  `InvalidStateTransitionError` - cancelling in-flight work isn't
  supported (it would need the worker's cooperation, which doesn't
  exist yet; see PROJECT_PLAN.md's cancellation design note).
- Unknown `taskId` → `404`.

## `GET /api/v1/dead-letters`

Administrative - requires the `X-Admin-Token` header to match
`PULSEQUEUE_ADMIN_TOKEN` (see `.env.example` and docs/threatModel.md).
Without it, or with the wrong value: `401`, `UnauthorizedError`.

```json
{"tasks": [ /* TaskDetailResponse objects, newest-dead-lettered first */ ]}
```

Optional `?limit=N` (default 50, max 100) - a basic listing; full
filtering/pagination like `GET /api/v1/tasks` isn't implemented for
this endpoint.

## `POST /api/v1/dead-letters/{taskId}/requeue`

Also admin-token protected. Resets `attemptCount` to 0 and returns the
task to `queued` with a fresh retry budget; its `task_attempts` history
is never deleted. Requeuing a task that isn't currently `dead_letter`
→ `409`, `InvalidStateTransitionError`.

Response (`200 OK`): the task's `TaskDetailResponse`, same shape as `GET /api/v1/tasks/{taskId}`.
