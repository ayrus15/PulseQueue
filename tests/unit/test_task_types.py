from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from pulsequeue.domain.errors import UnsupportedTaskTypeError
from pulsequeue.domain.taskTypes import ProcessFilePayload, validatePayload


def testUnsupportedTaskTypeIsRejected() -> None:
    with pytest.raises(UnsupportedTaskTypeError):
        validatePayload("deleteEverything", {})


def testGenerateReportAcceptsAValidPayload() -> None:
    result = validatePayload(
        "generateReport", {"reportName": "weekly-performance", "periodDays": 7}
    )
    assert result.model_dump() == {"reportName": "weekly-performance", "periodDays": 7}


def testGenerateReportRejectsMissingField() -> None:
    with pytest.raises(PydanticValidationError):
        validatePayload("generateReport", {"reportName": "weekly-performance"})


def testGenerateReportRejectsOutOfRangePeriod() -> None:
    with pytest.raises(PydanticValidationError):
        validatePayload("generateReport", {"reportName": "x", "periodDays": 0})


def testGenerateReportRejectsUnknownField() -> None:
    with pytest.raises(PydanticValidationError):
        validatePayload(
            "generateReport",
            {"reportName": "x", "periodDays": 1, "extraField": "not allowed"},
        )


def testCalculateMetricsAcceptsAValidPayload() -> None:
    result = validatePayload("calculateMetrics", {"metricName": "latency", "values": [1.0, 2.5]})
    assert result.model_dump() == {"metricName": "latency", "values": [1.0, 2.5]}


def testCalculateMetricsRejectsEmptyValues() -> None:
    with pytest.raises(PydanticValidationError):
        validatePayload("calculateMetrics", {"metricName": "latency", "values": []})


@pytest.mark.parametrize(
    "fileName",
    ["report.txt", "data-2026.csv", "a"],
)
def testProcessFileAcceptsSafeFileNames(fileName: str) -> None:
    payload = validatePayload("processFile", {"fileName": fileName})
    assert isinstance(payload, ProcessFilePayload)
    assert payload.isSafeFileName is True


@pytest.mark.parametrize(
    "fileName",
    [
        "../secret.txt",
        "/etc/passwd",
        "a/b.txt",
        "..\\windows\\system32",
        "..",
        "~/.ssh/id_rsa",
        "a\x00.txt",
        "..%2f..%2fetc%2fpasswd",
    ],
)
def testProcessFileRejectsPathTraversalAttempts(fileName: str) -> None:
    """Rejected at submission (a 422, not a task accepted then left to
    fail in the worker) - see ProcessFilePayload's field_validator.
    """
    with pytest.raises(PydanticValidationError):
        validatePayload("processFile", {"fileName": fileName})


def testSendNotificationAcceptsAValidPayload() -> None:
    result = validatePayload(
        "sendNotification", {"recipientName": "Hema C", "message": "Your report is ready."}
    )
    assert result.model_dump() == {
        "recipientName": "Hema C",
        "message": "Your report is ready.",
    }


def testSimulateFailureAcceptsAValidPayload() -> None:
    result = validatePayload("simulateFailure", {"failUntilAttempt": 2})
    assert result.model_dump() == {"failUntilAttempt": 2}


def testSimulateFailureRejectsNegativeAttempt() -> None:
    with pytest.raises(PydanticValidationError):
        validatePayload("simulateFailure", {"failUntilAttempt": -1})
