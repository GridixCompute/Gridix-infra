"""key brokering — jobs.wrapped_key (Session 9.3)

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("wrapped_key", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "wrapped_key")
