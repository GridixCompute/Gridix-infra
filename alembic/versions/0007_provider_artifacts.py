"""locality-aware scheduling — provider_artifacts (Session 8.5)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("digest", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "digest", name="uq_provider_artifact"),
    )
    op.create_index("ix_provider_artifacts_provider_id", "provider_artifacts", ["provider_id"])
    op.create_index("ix_provider_artifacts_digest", "provider_artifacts", ["digest"])


def downgrade() -> None:
    op.drop_index("ix_provider_artifacts_digest", table_name="provider_artifacts")
    op.drop_index("ix_provider_artifacts_provider_id", table_name="provider_artifacts")
    op.drop_table("provider_artifacts")
