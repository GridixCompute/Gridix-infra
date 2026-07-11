"""anti-spoofing — benchmark_reports.hardware_fingerprint (Session 11.6)

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "benchmark_reports",
        sa.Column("hardware_fingerprint", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_benchmark_reports_hardware_fingerprint",
        "benchmark_reports",
        ["hardware_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_benchmark_reports_hardware_fingerprint", table_name="benchmark_reports"
    )
    op.drop_column("benchmark_reports", "hardware_fingerprint")
