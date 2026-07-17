"""providers.wallet_address — the column the model declared but no migration created

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-18

``Provider.wallet_address`` (models.py) is read by on-chain settlement
(``chain/settlement.py``) and reconciliation (``chain/reconcile.py``), but no migration
ever added it: 0017 added ``wallet_address`` to ``developers`` only and the ``providers``
twin was never written. A fresh alembic-migrated deploy therefore had a ``providers``
table with no ``wallet_address`` column, so every ``SELECT providers`` raised
OperationalError — which blocked provider auth over the relay tunnel and every dispatch
that reads a provider. The hermetic suite never saw it: it builds the schema from the
model via ``Base.metadata.create_all`` (column present), while a real deploy runs
``alembic upgrade head`` (column absent).

Mirrors 0017's ``developers.wallet_address``: String(42), nullable, unique index — the
provider's wallet is its GridixEscrow payout address, so it is unique per provider.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("wallet_address", sa.String(length=42), nullable=True))
    op.create_index("ix_providers_wallet_address", "providers", ["wallet_address"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_providers_wallet_address", table_name="providers")
    op.drop_column("providers", "wallet_address")
