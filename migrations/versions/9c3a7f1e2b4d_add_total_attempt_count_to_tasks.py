"""add total_attempt_count to tasks

Revision ID: 9c3a7f1e2b4d
Revises: 4127c25b78b5
Create Date: 2026-11-01

Fixes a real bug found during Phase 9: ``tasks.attempt_count`` is reset
to 0 by an admin requeue (POST /api/v1/dead-letters/{id}/requeue), but
it was also the only source for ``task_attempts.attempt_number`` - which
must never repeat for a task across its whole lifetime, since requeue
deliberately keeps old attempt rows for audit (ADR 0003/PROJECT_PLAN.md
section 6). A task requeued from dead_letter and then failing again hit
the unique constraint on (task_id, attempt_number) and crashed the
worker with an unhandled IntegrityError. ``total_attempt_count`` is a
second, never-reset counter used for that purpose instead; see
src/pulsequeue/workers/worker.py and recovery/leaseRecovery.py's
comments at their use of it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c3a7f1e2b4d"
down_revision: str | None = "4127c25b78b5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("total_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    # Backfill from the real attempt history rather than leaving it at 0
    # for every pre-existing task - a task already past its first attempt
    # would otherwise immediately collide with its own existing
    # task_attempts rows the next time it's claimed.
    op.execute(
        """
        UPDATE tasks
        SET total_attempt_count = COALESCE(
            (SELECT MAX(attempt_number) FROM task_attempts WHERE task_attempts.task_id = tasks.id),
            attempt_count
        )
        """
    )
    # The application always sets this explicitly (see TaskRecord's
    # Python-side default) - no need for a permanent DB-side default,
    # matching every other column on this table.
    op.alter_column("tasks", "total_attempt_count", server_default=None)


def downgrade() -> None:
    op.drop_column("tasks", "total_attempt_count")
