"""initial schema — developers, providers, jobs, attempts, ledger, reputation, api_keys

Revision ID: 0001
Revises:
Create Date: 2026-07-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine:
    """JSONB on Postgres, JSON elsewhere — matches app.models.JSONVariant."""
    return sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "developers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("gpu_model", sa.String(length=120), nullable=True),
        sa.Column("gpu_vram_mb", sa.Integer(), nullable=False),
        sa.Column("cpu_cores", sa.Integer(), nullable=False),
        sa.Column("memory_mb", sa.Integer(), nullable=False),
        sa.Column("max_concurrent", sa.Integer(), nullable=False),
        sa.Column("reputation", sa.Float(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("reputation >= 0", name="ck_provider_reputation_nonneg"),
        sa.CheckConstraint("max_concurrent >= 1", name="ck_provider_max_concurrent"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_type", sa.String(length=20), nullable=False),
        sa.Column("developer_id", sa.Uuid(), nullable=True),
        sa.Column("provider_id", sa.Uuid(), nullable=True),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(developer_id IS NULL) <> (provider_id IS NULL)",
            name="ck_apikey_single_owner",
        ),
        sa.ForeignKeyConstraint(["developer_id"], ["developers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("developer_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("image_ref", sa.String(length=512), nullable=False),
        sa.Column("input_ref", sa.String(length=512), nullable=True),
        sa.Column("result_ref", sa.String(length=512), nullable=True),
        sa.Column("resource_spec", _json(), nullable=False),
        sa.Column("args", _json(), nullable=True),
        sa.Column("allow_egress", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("is_high_value", sa.Boolean(), nullable=False),
        sa.Column("redundancy", sa.Integer(), nullable=False),
        sa.Column("expected_output_hash", sa.String(length=64), nullable=True),
        sa.Column("proof", _json(), nullable=True),
        sa.Column("assigned_provider_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escrow_amount", sa.Numeric(20, 8), nullable=True),
        sa.Column("cost_final", sa.Numeric(20, 8), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("redundancy >= 1", name="ck_job_redundancy_positive"),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_job_timeout_positive"),
        sa.ForeignKeyConstraint(["developer_id"], ["developers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_provider_id"], ["providers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("developer_id", "idempotency_key", name="uq_job_idempotency"),
    )
    op.create_index("ix_jobs_developer_id", "jobs", ["developer_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_assigned_provider_id", "jobs", ["assigned_provider_id"])
    op.create_index("ix_jobs_status_kind", "jobs", ["status", "kind"])

    op.create_table(
        "job_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_ref", sa.String(length=512), nullable=True),
        sa.Column("proof", _json(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_attempt_number"),
    )
    op.create_index("ix_job_attempts_job_id", "job_attempts", ["job_id"])
    op.create_index("ix_job_attempts_provider_id", "job_attempts", ["provider_id"])

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entry_group", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("account", sa.String(length=20), nullable=False),
        sa.Column("account_ref", sa.Uuid(), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_ledger_amount_nonneg"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ledger_entries_entry_group", "ledger_entries", ["entry_group"])
    op.create_index("ix_ledger_entries_job_id", "ledger_entries", ["job_id"])
    op.create_index("ix_ledger_entries_account_ref", "ledger_entries", ["account_ref"])
    op.create_index("ix_ledger_account", "ledger_entries", ["account", "account_ref"])

    op.create_table(
        "reputation_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("score_after", sa.Float(), nullable=False),
        sa.Column("meta", _json(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reputation_events_provider_id", "reputation_events", ["provider_id"])
    op.create_index("ix_reputation_events_job_id", "reputation_events", ["job_id"])


def downgrade() -> None:
    op.drop_table("reputation_events")
    op.drop_table("ledger_entries")
    op.drop_table("job_attempts")
    op.drop_table("jobs")
    op.drop_table("api_keys")
    op.drop_table("providers")
    op.drop_table("developers")
