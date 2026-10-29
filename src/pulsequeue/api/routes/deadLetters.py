"""GET /api/v1/dead-letters and POST /api/v1/dead-letters/{taskId}/requeue.

Administrative - protected by requireAdminToken (see
api/dependencies.py and docs/threatModel.md).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.api.dependencies import getSession, requireAdminToken
from pulsequeue.api.schemas import (
    DeadLetterListResponse,
    TaskDetailResponse,
    taskRecordToDetailResponse,
)
from pulsequeue.persistence.repositories import TaskRepository

router = APIRouter(
    prefix="/api/v1/dead-letters",
    tags=["dead-letters"],
    dependencies=[Depends(requireAdminToken)],
)

MAX_PAGE_SIZE = 100


@router.get("", response_model=DeadLetterListResponse)
async def listDeadLetters(
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    session: AsyncSession = Depends(getSession),
) -> DeadLetterListResponse:
    repository = TaskRepository(session)
    records = await repository.listDeadLetterTasks(limit=limit)
    return DeadLetterListResponse(tasks=[taskRecordToDetailResponse(record) for record in records])


@router.post("/{taskId}/requeue", response_model=TaskDetailResponse)
async def requeueDeadLetter(
    taskId: uuid.UUID,
    session: AsyncSession = Depends(getSession),
) -> TaskDetailResponse:
    repository = TaskRepository(session)
    record = await repository.requeueDeadLetterTask(taskId, requeuedAt=datetime.now(UTC))
    return taskRecordToDetailResponse(record)
