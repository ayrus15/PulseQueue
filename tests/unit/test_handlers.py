from __future__ import annotations

from pathlib import Path

import pytest

from pulsequeue.domain.taskTypes import (
    TASK_TYPE_REGISTRY,
    CalculateMetricsPayload,
    GenerateReportPayload,
    ProcessFilePayload,
    SendNotificationPayload,
    SimulateFailurePayload,
)
from pulsequeue.workers import handlers
from pulsequeue.workers.handlers import ProcessFileError, resolveProcessFilePath
from pulsequeue.workers.registry import buildHandlerRegistry, getHandler


async def testGenerateReportReturnsASummary() -> None:
    result = await handlers.generateReport(
        GenerateReportPayload(reportName="weekly-performance", periodDays=7), attemptNumber=1
    )
    assert result["reportName"] == "weekly-performance"
    assert "weekly-performance" in str(result["summary"])


async def testCalculateMetricsComputesSummaryStatistics() -> None:
    result = await handlers.calculateMetrics(
        CalculateMetricsPayload(metricName="latency", values=[1.0, 2.0, 3.0]), attemptNumber=1
    )
    assert result == {"metricName": "latency", "count": 3, "mean": 2.0, "min": 1.0, "max": 3.0}


async def testSendNotificationSimulatesDelivery() -> None:
    result = await handlers.sendNotification(
        SendNotificationPayload(recipientName="Hema C", message="hi"), attemptNumber=1
    )
    assert result["channel"] == "simulated"
    assert result["recipientName"] == "Hema C"


async def testSimulateFailureRaisesUntilTheConfiguredAttempt() -> None:
    payload = SimulateFailurePayload(failUntilAttempt=2)
    with pytest.raises(RuntimeError):
        await handlers.simulateFailure(payload, attemptNumber=1)
    with pytest.raises(RuntimeError):
        await handlers.simulateFailure(payload, attemptNumber=2)
    result = await handlers.simulateFailure(payload, attemptNumber=3)
    assert result == {"failedAttempts": 2, "succeededOnAttempt": 3}


async def testSimulateFailureWithZeroNeverFails() -> None:
    payload = SimulateFailurePayload(failUntilAttempt=0)
    result = await handlers.simulateFailure(payload, attemptNumber=1)
    assert result["succeededOnAttempt"] == 1


def testResolveProcessFilePathAcceptsAFileInsideTheDirectory(tmp_path: Path) -> None:
    (tmp_path / "report.txt").write_text("hello")
    resolved = resolveProcessFilePath(tmp_path, "report.txt")
    assert resolved == (tmp_path / "report.txt").resolve()


def testResolveProcessFilePathRejectsEscapingTheDirectory(tmp_path: Path) -> None:
    sibling = tmp_path.parent / "outside.txt"
    with pytest.raises(ProcessFileError):
        resolveProcessFilePath(tmp_path, f"../{sibling.name}")


async def testProcessFileReadsAFileFromTheControlledDirectory(tmp_path: Path) -> None:
    filePath = tmp_path / "data.csv"
    filePath.write_bytes(b"a,b\n1,2\n")
    result = await handlers.processFile(
        ProcessFilePayload(fileName="data.csv"), attemptNumber=1, baseDirectory=tmp_path
    )
    assert result["lineCount"] == 2
    assert result["sizeBytes"] == filePath.stat().st_size


async def testProcessFileRaisesForAMissingFile(tmp_path: Path) -> None:
    with pytest.raises(ProcessFileError):
        await handlers.processFile(
            ProcessFilePayload(fileName="missing.csv"), attemptNumber=1, baseDirectory=tmp_path
        )


def testHandlerRegistryCoversExactlyTheRegisteredTaskTypes(tmp_path: Path) -> None:
    registry = buildHandlerRegistry(tmp_path)
    assert registry.keys() == TASK_TYPE_REGISTRY.keys()


def testGetHandlerRaisesForAnUnregisteredTaskType(tmp_path: Path) -> None:
    registry = buildHandlerRegistry(tmp_path)
    from pulsequeue.domain.errors import UnsupportedTaskTypeError

    with pytest.raises(UnsupportedTaskTypeError):
        getHandler(registry, "deleteEverything")
