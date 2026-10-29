from __future__ import annotations

import pytest
from pydantic import ValidationError

from pulsequeue.api.schemas import MAX_PAYLOAD_BYTES, TaskSubmissionRequest


def testAcceptsAWellFormedRequestUsingCamelCaseFields() -> None:
    request = TaskSubmissionRequest.model_validate(
        {
            "taskType": "generateReport",
            "payload": {"reportName": "x", "periodDays": 1},
            "maxAttempts": 3,
        }
    )
    assert request.taskType == "generateReport"
    assert request.maxAttempts == 3


def testMaxAttemptsIsOptional() -> None:
    request = TaskSubmissionRequest.model_validate({"taskType": "generateReport", "payload": {}})
    assert request.maxAttempts is None


def testRejectsMaxAttemptsBelowOne() -> None:
    with pytest.raises(ValidationError):
        TaskSubmissionRequest.model_validate(
            {"taskType": "generateReport", "payload": {}, "maxAttempts": 0}
        )


def testRejectsOversizedPayload() -> None:
    oversizedPayload = {"data": "x" * MAX_PAYLOAD_BYTES}
    with pytest.raises(ValidationError):
        TaskSubmissionRequest.model_validate(
            {"taskType": "generateReport", "payload": oversizedPayload}
        )


def testRejectsEmptyTaskType() -> None:
    with pytest.raises(ValidationError):
        TaskSubmissionRequest.model_validate({"taskType": "", "payload": {}})
