"""top-up history — ledger_entries.tx_hash

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-16

The watcher already knows the transaction each deposit came from (chain_events dedups on
tx_hash/log_index) and dropped it on the way to the ledger, so a developer saw a credit
appear with nothing tying it to the transfer they sent. Nullable: only rows that came from
a chain event have one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ledger_entries", sa.Column("tx_hash", sa.String(length=66), nullable=True))
    op.create_index("ix_ledger_entries_tx_hash", "ledger_entries", ["tx_hash"])


def downgrade() -> None:
    op.drop_index("ix_ledger_entries_tx_hash", table_name="ledger_entries")
    op.drop_column("ledger_entries", "tx_hash")
