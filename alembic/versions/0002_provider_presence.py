"""provider presence — connected_at, last_seen (Session 7.1)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("providers", sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_providers_last_seen", "providers", ["last_seen"])


def downgrade() -> None:
    op.drop_index("ix_providers_last_seen", table_name="providers")
    op.drop_column("providers", "last_seen")
    op.drop_column("providers", "connected_at")
