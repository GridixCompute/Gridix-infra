"""continuous health — providers.degraded + health_samples (Session 11.4)

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "providers",
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "health_samples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("gpu_temp_c", sa.Float(), nullable=True),
        sa.Column("throttling", sa.Boolean(), nullable=False),
        sa.Column("error_rate", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_samples_provider_id", "health_samples", ["provider_id"])


def downgrade() -> None:
    op.drop_index("ix_health_samples_provider_id", table_name="health_samples")
    op.drop_table("health_samples")
    op.drop_column("providers", "degraded")
