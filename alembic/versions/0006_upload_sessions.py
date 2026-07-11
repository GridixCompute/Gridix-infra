"""resumable uploads — upload_sessions (Session 8.4)

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("developer_id", sa.Uuid(), nullable=False),
        sa.Column("declared_digest", sa.String(length=64), nullable=True),
        sa.Column("blob_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["developer_id"], ["developers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_upload_sessions_developer_id", "upload_sessions", ["developer_id"])


def downgrade() -> None:
    op.drop_index("ix_upload_sessions_developer_id", table_name="upload_sessions")
    op.drop_table("upload_sessions")
