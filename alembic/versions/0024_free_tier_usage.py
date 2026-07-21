"""free_tier_usage — daily counters for the public, unauthenticated tier

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-21

The public free tier is bounded by rate rather than by balance, and the image half of that
bound is a per-visitor daily count. It lives in the database rather than in Redis or process
memory because the counter IS the limit: process memory resets on every deploy and Redis
resets on every restart unless persistence is configured, and either way the quota silently
reopens. For a limit whose whole job is to bound GPU spend, that is the expensive failure.

``anchor`` holds an already-hashed identity (a visitor cookie or an IP, salted and SHA-256'd
by ``free_tier.anchor_for``), never a raw address — the table is a counter, not a visitor
log, so it carries no personal data and needs no retention policy.

``day`` is a UTC calendar date stored as text, so the reset boundary is 00:00 UTC by
definition rather than by whatever timezone the database happens to be configured with. The
day being part of the key is also what makes the reset free: yesterday's row simply stops
being consulted, so there is no midnight job that can fail quietly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "free_tier_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("anchor", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("anchor", "day", name="uq_free_tier_usage_anchor_day"),
    )
    op.create_index("ix_free_tier_usage_day", "free_tier_usage", ["day"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_free_tier_usage_day", table_name="free_tier_usage")
    op.drop_table("free_tier_usage")
