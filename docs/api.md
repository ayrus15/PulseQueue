# API documentation

**Status: Phase 3 — task submission/retrieval and dead-letter
administration exist.** Listing with pagination/filtering and
cancellation are Phase 4; `/health/*` / `/metrics` are Phase 6.
Examples below are drawn directly from the integration tests, not
hand-written.

All endpoints are under `/api/v1`. Errors always have the shape:

```json
{"error": {"code": "TaskNotFoundError", "message": "Task not found: ..."}}
```

`code` is the raising exception's class name for domain errors
(`UnsupportedTaskTypeError`, `TaskNotFoundError`, `IdempotencyConflictError`,
`UnauthorizedError`, ...), or `RequestValidationError` / `ValidationError`
for malformed requests and payloads that fail their task type's schema,
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
- `status` can now be any of `queued`, `running`, `succeeded`, `failed`,
  `dead_letter` once a worker (Phase 2) has processed it; `cancelled`
  isn't reachable yet (Phase 4).

## `GET /api/v1/dead-letters`

Administrative - requires the `X-Admin-Token` header to match
`PULSEQUEUE_ADMIN_TOKEN` (see `.env.example` and docs/threatModel.md).
Without it, or with the wrong value: `401`, `UnauthorizedError`.

```json
{"tasks": [ /* TaskDetailResponse objects, newest-dead-lettered first */ ]}
```

Optional `?limit=N` (default 50, max 100). Full filtering/pagination
across all statuses is Phase 4.

## `POST /api/v1/dead-letters/{taskId}/requeue`

Also admin-token protected. Resets `attemptCount` to 0 and returns the
task to `queued` with a fresh retry budget; its `task_attempts` history
is never deleted. Requeuing a task that isn't currently `dead_letter`
→ `409`, `InvalidStateTransitionError`.

Response (`200 OK`): the task's `TaskDetailResponse`, same shape as `GET /api/v1/tasks/{taskId}`.
