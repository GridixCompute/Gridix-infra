"""dispute resolution — disputes (Session 10.1)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "disputes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("ruling_reason", sa.String(length=256), nullable=True),
        sa.Column("window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_disputes_provider_id", "disputes", ["provider_id"])
    op.create_index("ix_disputes_job_id", "disputes", ["job_id"])
    op.create_index("ix_disputes_state", "disputes", ["state"])


def downgrade() -> None:
    op.drop_index("ix_disputes_state", table_name="disputes")
    op.drop_index("ix_disputes_job_id", table_name="disputes")
    op.drop_index("ix_disputes_provider_id", table_name="disputes")
    op.drop_table("disputes")
