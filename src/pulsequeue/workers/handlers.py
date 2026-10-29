"""The five demo task handlers.

Each handler receives the already-validated payload model from
``domain/taskTypes.py`` plus the current attempt number, and returns a
JSON-serializable result dict that gets stored in ``tasks.result``.

Per PROJECT_PLAN.md section 8: no ``eval``, no shell execution, no
filesystem access outside ``processFile``'s single configured
directory, and no real external I/O - ``sendNotification`` only
simulates delivery.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from pulsequeue.domain.errors import PermanentTaskError
from pulsequeue.domain.taskTypes import (
    CalculateMetricsPayload,
    GenerateReportPayload,
    ProcessFilePayload,
    SendNotificationPayload,
    SimulateFailurePayload,
)


async def generateReport(payload: GenerateReportPayload, attemptNumber: int) -> dict[str, object]:
    return {
        "reportName": payload.reportName,
        "periodDays": payload.periodDays,
        "generatedAt": datetime.now(UTC).isoformat(),
        "summary": f"Report '{payload.reportName}' covering the last {payload.periodDays} day(s).",
    }


async def calculateMetrics(
    payload: CalculateMetricsPayload, attemptNumber: int
) -> dict[str, object]:
    values = payload.values
    return {
        "metricName": payload.metricName,
        "count": len(values),
        "mean": mean(values),
        "min": min(values),
        "max": max(values),
    }


class ProcessFileError(PermanentTaskError):
    """Raised for anything wrong with a processFile request - missing
    file, path escaping the controlled directory, or an unreadable file.
    Permanent: retrying won't make a missing or unsafe file appear.
    """


def resolveProcessFilePath(baseDirectory: Path, fileName: str) -> Path:
    """Resolve ``fileName`` inside ``baseDirectory``, refusing anything
    that would escape it - the second, filesystem-level check behind
    ``ProcessFilePayload.isSafeFileName``'s string-level one (ADR 0003).
    """
    resolvedBase = baseDirectory.resolve()
    resolvedTarget = (resolvedBase / fileName).resolve()
    if resolvedBase not in resolvedTarget.parents and resolvedTarget != resolvedBase:
        raise ProcessFileError(f"{fileName!r} resolves outside the controlled directory")
    return resolvedTarget


async def processFile(
    payload: ProcessFilePayload, attemptNumber: int, baseDirectory: Path
) -> dict[str, object]:
    if not payload.isSafeFileName:
        raise ProcessFileError(f"Unsafe file name: {payload.fileName!r}")

    targetPath = resolveProcessFilePath(baseDirectory, payload.fileName)
    if not targetPath.is_file():
        raise ProcessFileError(f"File not found: {payload.fileName!r}")

    content = targetPath.read_text(encoding="utf-8", errors="replace")
    return {
        "fileName": payload.fileName,
        "sizeBytes": targetPath.stat().st_size,
        "lineCount": content.count("\n") + (1 if content and not content.endswith("\n") else 0),
    }


async def sendNotification(
    payload: SendNotificationPayload, attemptNumber: int
) -> dict[str, object]:
    return {
        "recipientName": payload.recipientName,
        "message": payload.message,
        "deliveredAt": datetime.now(UTC).isoformat(),
        "channel": "simulated",
    }


async def simulateFailure(payload: SimulateFailurePayload, attemptNumber: int) -> dict[str, object]:
    """Development/testing only - deliberately fails until ``failUntilAttempt``
    to exercise retry handling; never registered for production use beyond
    that purpose.
    """
    if attemptNumber <= payload.failUntilAttempt:
        raise RuntimeError(
            f"Simulated failure on attempt {attemptNumber} (failUntilAttempt="
            f"{payload.failUntilAttempt})"
        )
    return {"failedAttempts": payload.failUntilAttempt, "succeededOnAttempt": attemptNumber}
