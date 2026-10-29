"""Request/response schemas for the public API.

Fields are camelCase on the wire, matching PROJECT_PLAN.md's contract
examples (``taskId``, ``statusUrl``, ...); Python attribute names match
directly via ``alias_generator`` instead of a separate alias per field.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

MAX_PAYLOAD_BYTES = 32 * 1024
"""A deliberately small cap: these are demo handlers operating on small
inputs (report names, metric lists, short messages), not a bulk-data API."""


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TaskSubmissionRequest(_CamelModel):
    taskType: str = Field(min_length=1, max_length=100)
    payload: dict[str, object] = Field(default_factory=dict)
    maxAttempts: int | None = Field(default=None, ge=1, le=20)

    @field_validator("payload")
    @classmethod
    def checkPayloadSize(cls, payload: dict[str, object]) -> dict[str, object]:
        encodedSize = len(json.dumps(payload).encode("utf-8"))
        if encodedSize > MAX_PAYLOAD_BYTES:
            raise ValueError(
                f"payload exceeds the {MAX_PAYLOAD_BYTES}-byte limit ({encodedSize} bytes)"
            )
        return payload


class TaskSubmissionResponse(_CamelModel):
    taskId: uuid.UUID
    status: str
    statusUrl: str


class TaskDetailResponse(_CamelModel):
    taskId: uuid.UUID
    taskType: str
    status: str
    attemptCount: int
    maxAttempts: int
    createdAt: datetime
    scheduledAt: datetime
    startedAt: datetime | None
    completedAt: datetime | None
    updatedAt: datetime
    result: dict[str, object] | None
    lastErrorCode: str | None
    lastErrorMessage: str | None
    correlationId: str


class ErrorDetail(_CamelModel):
    code: str
    message: str


class ErrorResponse(_CamelModel):
    error: ErrorDetail
