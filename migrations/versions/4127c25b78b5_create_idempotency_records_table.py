"""create idempotency_records table

Revision ID: 4127c25b78b5
Revises: aafb62e2018d
Create Date: 2026-10-29

Written by hand to match src/pulsequeue/persistence/models.py's
IdempotencyRecord. See ADR 0004 for the uniqueness/fingerprint design.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4127c25b78b5"
down_revision: str | None = "aafb62e2018d"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "scope", "idempotency_key", name="uq_idempotency_records_scope_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
