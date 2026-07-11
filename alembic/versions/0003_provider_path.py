"""provider connection path — path_type, path_established_at (Session 7.4)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("path_type", sa.String(length=10), nullable=True))
    op.add_column(
        "providers",
        sa.Column("path_established_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("providers", "path_established_at")
    op.drop_column("providers", "path_type")
