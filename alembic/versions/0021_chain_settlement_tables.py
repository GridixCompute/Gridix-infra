"""chain settlement tables — the four chain_* models that never had a migration

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-18

ChainSettlement, ProviderSettlement, ChainEvent, ChainCursor (models.py) existed only in the
model — no migration ever created them. Latent because chain is off by default
(GRIDIX_CHAIN_ENABLED=false), but a fresh ``alembic upgrade head`` produces a schema without
them, so the moment chain is switched on the watcher/settlement code hits OperationalError on
the first SELECT. The drift gate #20 was scoped to columns only and did not catch whole missing
tables; the widened gate (test_migration_schema_drift.py) does.

Created here from the model, faithfully — columns, types, FKs, constraints, and indexes. The
widened gate validates the match. Additive only: it creates tables and their indexes, nothing
existing is touched.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# models.py: JSONVariant = JSON().with_variant(JSONB, "postgresql")
_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "chain_settlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "settle_batch",
                "deposit_settlement",
                "debit",
                name="chain_tx_kind",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "submitted",
                "confirmed",
                "failed",
                name="chain_tx_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("batch_key", sa.String(length=200), nullable=False),
        sa.Column("nonce", sa.BigInteger(), nullable=True),
        sa.Column("tx_hash", sa.String(length=66), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("payload", _JSON, nullable=True),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chain_settlements_status", "chain_settlements", ["status"], unique=False)
    op.create_index(
        "ix_chain_settlements_batch_key", "chain_settlements", ["batch_key"], unique=True
    )
    op.create_index("ix_chain_settlements_nonce", "chain_settlements", ["nonce"], unique=False)
    op.create_index("ix_chain_settlements_tx_hash", "chain_settlements", ["tx_hash"], unique=True)

    op.create_table(
        "provider_settlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("settlement_id", sa.Uuid(), nullable=False),
        sa.Column("amount_units", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount_units >= 0", name="ck_provsettle_nonneg"),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["settlement_id"], ["chain_settlements.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_settlements_provider_id", "provider_settlements", ["provider_id"], unique=False
    )
    op.create_index(
        "ix_provider_settlements_settlement_id",
        "provider_settlements",
        ["settlement_id"],
        unique=False,
    )

    op.create_table(
        "chain_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_name", sa.String(length=32), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_hash", sa.String(length=66), nullable=False),
        sa.Column("address", sa.String(length=42), nullable=False),
        sa.Column("args", _JSON, nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tx_hash", "log_index", name="uq_chain_event_log"),
    )
    op.create_index("ix_chain_events_event_name", "chain_events", ["event_name"], unique=False)
    op.create_index("ix_chain_events_tx_hash", "chain_events", ["tx_hash"], unique=False)
    op.create_index("ix_chain_events_block_number", "chain_events", ["block_number"], unique=False)
    op.create_index("ix_chain_events_confirmed", "chain_events", ["confirmed"], unique=False)
    op.create_index("ix_chain_events_processed", "chain_events", ["processed"], unique=False)

    op.create_table(
        "chain_cursors",
        sa.Column("stream", sa.String(length=32), nullable=False),
        sa.Column("last_scanned_block", sa.BigInteger(), nullable=False),
        sa.Column("head_block_hash", sa.String(length=66), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("stream"),
    )


def downgrade() -> None:
    op.drop_table("chain_cursors")
    op.drop_index("ix_chain_events_processed", table_name="chain_events")
    op.drop_index("ix_chain_events_confirmed", table_name="chain_events")
    op.drop_index("ix_chain_events_block_number", table_name="chain_events")
    op.drop_index("ix_chain_events_tx_hash", table_name="chain_events")
    op.drop_index("ix_chain_events_event_name", table_name="chain_events")
    op.drop_table("chain_events")
    op.drop_index("ix_provider_settlements_settlement_id", table_name="provider_settlements")
    op.drop_index("ix_provider_settlements_provider_id", table_name="provider_settlements")
    op.drop_table("provider_settlements")  # FK to chain_settlements → drop before it
    op.drop_index("ix_chain_settlements_tx_hash", table_name="chain_settlements")
    op.drop_index("ix_chain_settlements_nonce", table_name="chain_settlements")
    op.drop_index("ix_chain_settlements_batch_key", table_name="chain_settlements")
    op.drop_index("ix_chain_settlements_status", table_name="chain_settlements")
    op.drop_table("chain_settlements")
