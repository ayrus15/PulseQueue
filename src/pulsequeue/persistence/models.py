"""SQLAlchemy ORM models. PostgreSQL-only (JSONB, native UUID) - see ADR 0001."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TaskRecord(Base):
    """A single task: its payload, lifecycle state, and audit timestamps.

    Column choices follow PROJECT_PLAN.md section 9 and ADR 0003 - the
    lease fields are set by the worker's claim query in
    persistence/repositories.py.
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


class TaskAttemptRecord(Base):
    """One row per attempt a worker makes at a task - the audit trail
    `TaskRecord.attemptCount` alone can't provide (which worker, when,
    how it ended). See ADR 0003 and PROJECT_PLAN.md section 9.
    """

    __tablename__ = "task_attempts"
    __table_args__ = (
        # Supports GET /api/v1/tasks/{taskId} showing attempt history, and the
        # recovery poll's "find this task's open attempt" lookup.
        Index("ix_task_attempts_task_id", "task_id"),
        UniqueConstraint(
            "task_id", "attempt_number", name="uq_task_attempts_task_id_attempt_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    taskId: Mapped[uuid.UUID] = mapped_column(
        "task_id", ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    attemptNumber: Mapped[int] = mapped_column("attempt_number", Integer, nullable=False)
    workerId: Mapped[str] = mapped_column("worker_id", String(200), nullable=False)

    startedAt: Mapped[datetime] = mapped_column(
        "started_at", DateTime(timezone=True), nullable=False
    )
    endedAt: Mapped[datetime | None] = mapped_column(
        "ended_at", DateTime(timezone=True), nullable=True
    )

    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    errorCode: Mapped[str | None] = mapped_column("error_code", String(100), nullable=True)
    errorMessage: Mapped[str | None] = mapped_column("error_message", Text, nullable=True)
    durationMs: Mapped[int | None] = mapped_column("duration_ms", Integer, nullable=True)


class IdempotencyRecord(Base):
    """Maps a client's ``(scope, idempotencyKey)`` to the task it created.

    The unique constraint is the actual duplicate-prevention mechanism
    (ADR 0004) - application code only decides what to do when it's hit,
    never whether duplicates are possible.
    """

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_records_scope_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotencyKey: Mapped[str] = mapped_column("idempotency_key", String(200), nullable=False)
    requestFingerprint: Mapped[str] = mapped_column(
        "request_fingerprint", String(64), nullable=False
    )
    taskId: Mapped[uuid.UUID] = mapped_column(
        "task_id", ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    createdAt: Mapped[datetime] = mapped_column(
        "created_at", DateTime(timezone=True), nullable=False
    )
