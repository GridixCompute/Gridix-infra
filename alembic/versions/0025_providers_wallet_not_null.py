"""providers.wallet_address NOT NULL — a provider is a capability of a wallet address

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-23

The legacy ``POST /providers`` factory predated wallet login and minted providers with
``wallet_address`` NULL — records no wallet session could ever reach, because console
access resolves the provider FROM the session's address (``require_provider_principal``).
That route is deleted in this change; the only remaining creation path is
``POST /providers/onboard``, which always binds the row to the authenticated address.

This migration closes the hole at the schema level rather than hiding it: with the
column NOT NULL, re-introducing any wallet-less construction path is rejected by the
database itself, not just by review.

Safe without a backfill: no database is deployed anywhere yet, so there are zero
existing rows — after a deploy this same change would need a claim path, a data
migration, and a security review.

Batch mode because SQLite (the CI round-trip target) cannot ALTER a column in place;
on Postgres it degrades to a plain ``ALTER TABLE ... SET NOT NULL``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.alter_column("wallet_address", existing_type=sa.String(length=42), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.alter_column("wallet_address", existing_type=sa.String(length=42), nullable=True)
