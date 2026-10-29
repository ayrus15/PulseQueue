from __future__ import annotations

from pulsequeue.domain.idempotency import computeRequestFingerprint


def testSameLogicalRequestProducesTheSameFingerprint() -> None:
    a = computeRequestFingerprint("generateReport", {"reportName": "x", "periodDays": 1}, 4)
    b = computeRequestFingerprint("generateReport", {"reportName": "x", "periodDays": 1}, 4)
    assert a == b


def testKeyOrderDoesNotAffectTheFingerprint() -> None:
    a = computeRequestFingerprint("generateReport", {"reportName": "x", "periodDays": 1}, 4)
    b = computeRequestFingerprint("generateReport", {"periodDays": 1, "reportName": "x"}, 4)
    assert a == b


def testDifferentPayloadChangesTheFingerprint() -> None:
    a = computeRequestFingerprint("generateReport", {"reportName": "x", "periodDays": 1}, 4)
    b = computeRequestFingerprint("generateReport", {"reportName": "y", "periodDays": 1}, 4)
    assert a != b


def testDifferentMaxAttemptsChangesTheFingerprint() -> None:
    a = computeRequestFingerprint("generateReport", {"reportName": "x"}, 4)
    b = computeRequestFingerprint("generateReport", {"reportName": "x"}, 5)
    assert a != b


def testDifferentTaskTypeChangesTheFingerprint() -> None:
    a = computeRequestFingerprint("generateReport", {}, 4)
    b = computeRequestFingerprint("calculateMetrics", {}, 4)
    assert a != b


def testFingerprintIsAHexSha256Digest() -> None:
    fingerprint = computeRequestFingerprint("generateReport", {}, 4)
    assert len(fingerprint) == 64
    int(fingerprint, 16)  # raises ValueError if not valid hex
