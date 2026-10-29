"""POST /api/v1/tasks and GET /api/v1/tasks/{taskId}.

Listing, cancellation, and dead-letter administration are added in later
phases (Phase 4) - see PROJECT_PLAN.md's implementation order.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.api.dependencies import getSession
from pulsequeue.api.schemas import TaskDetailResponse, TaskSubmissionRequest, TaskSubmissionResponse
from pulsequeue.core.config import Settings, getSettings
from pulsequeue.domain.taskTypes import validatePayload
from pulsequeue.persistence.models import TaskRecord
from pulsequeue.persistence.repositories import NewTaskInput, TaskRepository

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
    session: AsyncSession = Depends(getSession),
    settings: Settings = Depends(getSettings),
) -> TaskSubmissionResponse:
    # Validates the task type and payload shape before anything is persisted,
    # per FR1: unsupported types and malformed payloads never reach the database.
    validatePayload(submission.taskType, submission.payload)

    repository = TaskRepository(session)
    record = await repository.createTask(
        NewTaskInput(
            taskType=submission.taskType,
            payload=submission.payload,
            maxAttempts=submission.maxAttempts or settings.defaultMaxAttempts,
            correlationId=str(uuid.uuid4()),
        )
    )
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
