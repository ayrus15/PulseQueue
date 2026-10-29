# API documentation

**Status: Phase 1 — only the two endpoints below exist.** Listing,
cancellation, dead-letter administration, and `/health/*` / `/metrics`
are specified in [`PROJECT_PLAN.md`](../PROJECT_PLAN.md) sections 7-8
but not implemented until Phase 4/6. Examples below are drawn directly
from `tests/integration/test_task_api.py`, not hand-written.

All endpoints are under `/api/v1`. Errors always have the shape:

```json
{"error": {"code": "TaskNotFoundError", "message": "Task not found: ..."}}
```

`code` is the raising exception's class name for domain errors
(`UnsupportedTaskTypeError`, `TaskNotFoundError`, ...), or
`RequestValidationError` / `ValidationError` for malformed requests and
payloads that fail their task type's schema, or `InternalServerError`
for anything unexpected (never a raw stack trace).

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

Response (`201 Created`):

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

Not yet implemented: the `Idempotency-Key` header (Phase 3).

## `GET /api/v1/tasks/{taskId}`

Response (`200 OK`):

```json
{
  "taskId": "b3f1...-uuid",
  "taskType": "generateReport",
  "status": "queued",
  "attemptCount": 0,
  "maxAttempts": 4,
  "createdAt": "2026-10-29T12:00:00+00:00",
  "scheduledAt": "2026-10-29T12:00:00+00:00",
  "startedAt": null,
  "completedAt": null,
  "updatedAt": "2026-10-29T12:00:00+00:00",
  "result": null,
  "lastErrorCode": null,
  "lastErrorMessage": null,
  "correlationId": "c9a2...-uuid"
}
```

- Unknown or malformed `taskId` → `404` (`TaskNotFoundError`) if it's a
  valid UUID that doesn't exist, `422` if it isn't a valid UUID at all.
- Every status stays `queued` right now - no worker exists yet to move
  a task to `running` or beyond (Phase 2).
