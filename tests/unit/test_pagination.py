from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from pulsequeue.api.pagination import decodeCursor, encodeCursor
from pulsequeue.domain.errors import ValidationError


def testEncodeThenDecodeRoundTrips() -> None:
    createdAt = datetime(2026, 1, 1, 12, 30, 0, tzinfo=UTC)
    taskId = uuid.uuid4()

    cursor = encodeCursor(createdAt, taskId)
    decodedCreatedAt, decodedId = decodeCursor(cursor)

    assert decodedCreatedAt == createdAt
    assert decodedId == taskId


def testDecodeRejectsGarbageInput() -> None:
    with pytest.raises(ValidationError):
        decodeCursor("not-a-valid-cursor")


def testDecodeRejectsValidBase64WithWrongShape() -> None:
    import base64

    garbage = base64.urlsafe_b64encode(b"no-pipe-separator").decode("ascii")
    with pytest.raises(ValidationError):
        decodeCursor(garbage)
