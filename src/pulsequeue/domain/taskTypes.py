"""The registered task type allowlist and each type's payload schema.

Task handlers themselves are not implemented until Phase 2 (they run in
the worker process). This module only defines what a valid submission
looks like for each type, so the API can reject unsupported types and
malformed payloads before anything is persisted - handler execution will
reuse these same schemas.

Demo task types and their use of the sample names (Sachin Yadav, Hema C,
Arjun Ramesh, Shaurya Mishra, Shubham Kundu) are illustrative test data
only, per PROJECT_PLAN.md section 2 - not real customer identities.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from pulsequeue.domain.errors import UnsupportedTaskTypeError

_SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class GenerateReportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reportName: str = Field(min_length=1, max_length=100)
    periodDays: int = Field(ge=1, le=365)


class CalculateMetricsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metricName: str = Field(min_length=1, max_length=100)
    values: list[float] = Field(min_length=1, max_length=1000)


class ProcessFilePayload(BaseModel):
    """``fileName`` is a bare filename, never a path.

    The worker resolves it against a single configured directory; no
    path separators or traversal sequences are accepted here, as the
    first of two independent checks (ADR 0003's threat model repeats the
    second, filesystem-level check the worker performs).
    """

    model_config = ConfigDict(extra="forbid")

    fileName: str = Field(min_length=1, max_length=128)

    @property
    def isSafeFileName(self) -> bool:
        return bool(_SAFE_FILENAME_PATTERN.match(self.fileName)) and ".." not in self.fileName


class SendNotificationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipientName: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)


class SimulateFailurePayload(BaseModel):
    """Development/testing only - deliberately fails to exercise retry logic."""

    model_config = ConfigDict(extra="forbid")

    failUntilAttempt: int = Field(ge=0, le=20)


TASK_TYPE_REGISTRY: dict[str, type[BaseModel]] = {
    "generateReport": GenerateReportPayload,
    "calculateMetrics": CalculateMetricsPayload,
    "processFile": ProcessFilePayload,
    "sendNotification": SendNotificationPayload,
    "simulateFailure": SimulateFailurePayload,
}


def validatePayload(taskType: str, payload: dict[str, object]) -> BaseModel:
    """Validate ``payload`` against the schema registered for ``taskType``.

    Raises UnsupportedTaskTypeError if ``taskType`` isn't registered, or
    pydantic.ValidationError (allowed to propagate - the API layer maps it
    to a 422 with field-level detail) if the payload doesn't match the
    schema.
    """
    schema = TASK_TYPE_REGISTRY.get(taskType)
    if schema is None:
        raise UnsupportedTaskTypeError(taskType)
    return schema.model_validate(payload)
