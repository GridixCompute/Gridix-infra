"""bandwidth accounting — bandwidth_events (Session 7.7)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bandwidth_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("num_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("num_bytes >= 0", name="ck_bandwidth_nonneg"),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bandwidth_events_provider_id", "bandwidth_events", ["provider_id"])
    op.create_index("ix_bandwidth_events_job_id", "bandwidth_events", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_bandwidth_events_job_id", table_name="bandwidth_events")
    op.drop_index("ix_bandwidth_events_provider_id", table_name="bandwidth_events")
    op.drop_table("bandwidth_events")
