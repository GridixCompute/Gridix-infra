"""inference dispatch — provider_models (which node serves which model)

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "model", name="uq_provider_model"),
    )
    op.create_index("ix_provider_models_provider_id", "provider_models", ["provider_id"])
    op.create_index("ix_provider_models_model", "provider_models", ["model"])


def downgrade() -> None:
    op.drop_index("ix_provider_models_model", table_name="provider_models")
    op.drop_index("ix_provider_models_provider_id", table_name="provider_models")
    op.drop_table("provider_models")
