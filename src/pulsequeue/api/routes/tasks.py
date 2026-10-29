"""POST /api/v1/tasks and GET /api/v1/tasks/{taskId}.

Listing, cancellation, and dead-letter administration are added in later
phases (Phase 4) - see PROJECT_PLAN.md's implementation order.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.api.dependencies import getRedisClient, getSession
from pulsequeue.api.schemas import TaskDetailResponse, TaskSubmissionRequest, TaskSubmissionResponse
from pulsequeue.core.config import Settings, getSettings
from pulsequeue.domain.taskTypes import validatePayload
from pulsequeue.persistence.models import TaskRecord
from pulsequeue.persistence.repositories import NewTaskInput, TaskRepository
from pulsequeue.queueing.redisQueue import notifyTaskReady

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def _toDetailResponse(record: TaskRecord) -> TaskDetailResponse:
    return TaskDetailResponse(
        taskId=record.id,
        taskType=record.taskType,
        status=record.status,
        attemptCount=record.attemptCount,
        maxAttempts=record.maxAttempts,
        createdAt=record.createdAt,
        scheduledAt=record.scheduledAt,
        startedAt=record.startedAt,
        completedAt=record.completedAt,
        updatedAt=record.updatedAt,
        result=record.result,
        lastErrorCode=record.lastErrorCode,
        lastErrorMessage=record.lastErrorMessage,
        correlationId=record.correlationId,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskSubmissionResponse)
async def submitTask(
    submission: TaskSubmissionRequest,
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
        correlationId=str(uuid.uuid4()),
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


@router.get("/{taskId}", response_model=TaskDetailResponse)
async def getTask(
    taskId: uuid.UUID,
    session: AsyncSession = Depends(getSession),
) -> TaskDetailResponse:
    repository = TaskRepository(session)
    record = await repository.getTaskById(taskId)
    return _toDetailResponse(record)
