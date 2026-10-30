"""POST /api/v1/tasks, GET /api/v1/tasks, GET /api/v1/tasks/{taskId},
and POST /api/v1/tasks/{taskId}/cancel.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.api.dependencies import getRedisClient, getSession
from pulsequeue.api.pagination import MAX_PAGE_SIZE, decodeCursor, encodeCursor
from pulsequeue.api.schemas import (
    TaskDetailResponse,
    TaskListResponse,
    TaskSubmissionRequest,
    TaskSubmissionResponse,
    taskRecordToDetailResponse,
)
from pulsequeue.core.config import Settings, getSettings
from pulsequeue.domain.errors import ValidationError
from pulsequeue.domain.models import TaskStatus
from pulsequeue.domain.taskTypes import TASK_TYPE_REGISTRY, validatePayload
from pulsequeue.persistence.repositories import NewTaskInput, TaskRepository
from pulsequeue.queueing.redisQueue import notifyTaskReady

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskSubmissionResponse)
async def submitTask(
    submission: TaskSubmissionRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(getSession),
    settings: Settings = Depends(getSettings),
    redisClient: Redis = Depends(getRedisClient),
    idempotencyKey: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TaskSubmissionResponse:
    # Validates the task type and payload shape before anything is persisted,
    # per FR1: unsupported types and malformed payloads never reach the database.
    validatePayload(submission.taskType, submission.payload)

    repository = TaskRepository(session)
    newTask = NewTaskInput(
        taskType=submission.taskType,
        payload=submission.payload,
        maxAttempts=submission.maxAttempts or settings.defaultMaxAttempts,
        # The request's correlation ID (client-supplied via X-Correlation-Id,
        # or generated - see api/middleware.py) ties this task's own logs
        # back to the request that created it.
        correlationId=request.state.correlationId,
    )

    if idempotencyKey is None:
        record = await repository.createTask(newTask)
    else:
        result = await repository.createTaskIdempotently(newTask, idempotencyKey)
        record = result.task
        if not result.wasCreated:
            # Reusing an existing request is not "created" - ADR 0004.
            response.status_code = status.HTTP_200_OK

    # Best-effort only (ADR 0002) - the task is already durably committed
    # above regardless of whether this notification is delivered.
    await notifyTaskReady(redisClient)

    return TaskSubmissionResponse(
        taskId=record.id,
        status=record.status,
        statusUrl=f"/api/v1/tasks/{record.id}",
    )


@router.get("", response_model=TaskListResponse)
async def listTasks(
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    status_: str | None = Query(default=None, alias="status"),
    taskType: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    session: AsyncSession = Depends(getSession),
) -> TaskListResponse:
    if status_ is not None and status_ not in {s.value for s in TaskStatus}:
        raise ValidationError(f"Unknown status filter: {status_!r}")
    if taskType is not None and taskType not in TASK_TYPE_REGISTRY:
        raise ValidationError(f"Unknown taskType filter: {taskType!r}")
    afterCursor = decodeCursor(cursor) if cursor is not None else None

    repository = TaskRepository(session)
    # Fetch one extra row to know whether another page exists, without a
    # separate COUNT query.
    records = await repository.listTasks(
        limit=limit + 1,
        statusFilter=status_,
        taskTypeFilter=taskType,
        afterCursor=afterCursor,
    )

    hasNextPage = len(records) > limit
    pageRecords = records[:limit]
    nextCursor = (
        encodeCursor(pageRecords[-1].createdAt, pageRecords[-1].id)
        if hasNextPage and pageRecords
        else None
    )
    return TaskListResponse(
        tasks=[taskRecordToDetailResponse(record) for record in pageRecords],
        nextCursor=nextCursor,
    )


@router.get("/{taskId}", response_model=TaskDetailResponse)
async def getTask(
    taskId: uuid.UUID,
    session: AsyncSession = Depends(getSession),
) -> TaskDetailResponse:
    repository = TaskRepository(session)
    record = await repository.getTaskById(taskId)
    return taskRecordToDetailResponse(record)


@router.post("/{taskId}/cancel", response_model=TaskDetailResponse)
async def cancelTask(
    taskId: uuid.UUID,
    session: AsyncSession = Depends(getSession),
) -> TaskDetailResponse:
    repository = TaskRepository(session)
    record = await repository.cancelTask(taskId, cancelledAt=datetime.now(UTC))
    return taskRecordToDetailResponse(record)
