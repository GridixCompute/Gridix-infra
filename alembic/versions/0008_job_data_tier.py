"""confidential compute — jobs.data_tier (Session 9.1)

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("data_tier", sa.String(length=24), nullable=False, server_default="public"),
    )


def downgrade() -> None:
    op.drop_column("jobs", "data_tier")
