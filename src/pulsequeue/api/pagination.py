"""Opaque cursor encode/decode for stable task listing pagination.

The cursor is ``(createdAt, id)`` - matching the ``ix_tasks_created_at_id``
index and ``ORDER BY created_at, id`` - so new inserts never shift an
already-issued page (FR3).
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime

from pulsequeue.domain.errors import ValidationError

MAX_PAGE_SIZE = 100


def encodeCursor(createdAt: datetime, taskId: uuid.UUID) -> str:
    raw = f"{createdAt.isoformat()}|{taskId}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decodeCursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        createdAtPart, idPart = raw.split("|", 1)
        return datetime.fromisoformat(createdAtPart), uuid.UUID(idPart)
    except Exception as exc:
        raise ValidationError(f"Invalid pagination cursor: {cursor!r}") from exc
