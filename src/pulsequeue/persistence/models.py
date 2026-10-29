"""SQLAlchemy ORM models. PostgreSQL-only (JSONB, native UUID) - see ADR 0001.

Only the ``tasks`` table exists so far. ``task_attempts`` (Phase 2) and
``idempotency_records`` (Phase 3) are added in their own migrations when
the code that writes to them lands, per PROJECT_PLAN.md's phased order.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TaskRecord(Base):
    """A single task: its payload, lifecycle state, and audit timestamps.

    Column choices follow PROJECT_PLAN.md section 9 and ADR 0003 (lease
    fields support Phase 2's worker claiming; they are unused - always
    NULL - until then).
    """

    __tablename__ = "tasks"
    __table_args__ = (
        # Supports the Phase 2 worker poll query:
        # WHERE status = 'queued' AND scheduled_at <= now() ORDER BY scheduled_at.
        Index("ix_tasks_status_scheduled_at", "status", "scheduled_at"),
        # Supports stable, deterministic pagination for GET /api/v1/tasks (Phase 4):
        # ORDER BY created_at, id so new inserts never shift existing pages.
        Index("ix_tasks_created_at_id", "created_at", "id"),
        # Supports GET /api/v1/tasks?taskType=... filtering (Phase 4).
        Index("ix_tasks_task_type", "task_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    taskType: Mapped[str] = mapped_column("task_type", String(100), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attemptCount: Mapped[int] = mapped_column("attempt_count", Integer, nullable=False, default=0)
    maxAttempts: Mapped[int] = mapped_column("max_attempts", Integer, nullable=False)

    createdAt: Mapped[datetime] = mapped_column(
        "created_at", DateTime(timezone=True), nullable=False
    )
    scheduledAt: Mapped[datetime] = mapped_column(
        "scheduled_at", DateTime(timezone=True), nullable=False
    )
    startedAt: Mapped[datetime | None] = mapped_column(
        "started_at", DateTime(timezone=True), nullable=True
    )
    completedAt: Mapped[datetime | None] = mapped_column(
        "completed_at", DateTime(timezone=True), nullable=True
    )
    updatedAt: Mapped[datetime] = mapped_column(
        "updated_at", DateTime(timezone=True), nullable=False
    )

    result: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    lastErrorCode: Mapped[str | None] = mapped_column("last_error_code", String(100), nullable=True)
    lastErrorMessage: Mapped[str | None] = mapped_column("last_error_message", Text, nullable=True)

    leaseOwner: Mapped[str | None] = mapped_column("lease_owner", String(200), nullable=True)
    leaseExpiresAt: Mapped[datetime | None] = mapped_column(
        "lease_expires_at", DateTime(timezone=True), nullable=True
    )

    correlationId: Mapped[str] = mapped_column("correlation_id", String(64), nullable=False)
