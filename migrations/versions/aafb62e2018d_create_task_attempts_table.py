"""create task_attempts table

Revision ID: aafb62e2018d
Revises: 520e43ca9fd2
Create Date: 2026-10-29

Written by hand to match src/pulsequeue/persistence/models.py's
TaskAttemptRecord. See ADR 0003 for why this table exists separately
from tasks.attempt_count.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "aafb62e2018d"
down_revision: str | None = "520e43ca9fd2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=30), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "task_id", "attempt_number", name="uq_task_attempts_task_id_attempt_number"
        ),
    )
    op.create_index("ix_task_attempts_task_id", "task_attempts", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_task_attempts_task_id", table_name="task_attempts")
    op.drop_table("task_attempts")
