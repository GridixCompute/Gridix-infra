"""wallet auth — developers.wallet_address, auth_nonces, api_key session fields

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-16

``developers.wallet_address`` is added here even though it arrived with the Session 13
models: no migration ever created it, so a database built from migrations lacked a column
that every ``SELECT developers`` emits — which 500s each authenticated request. Wallet
sign-in makes that column load-bearing, so it is restored as part of this change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The wallet is the developer's identity AND its GridixEscrow depositor — one
    # address, so unique.
    op.add_column("developers", sa.Column("wallet_address", sa.String(length=42), nullable=True))
    op.create_index("ix_developers_wallet_address", "developers", ["wallet_address"], unique=True)

    # Session keys expire; user-generated CLI keys do not (NULL).
    op.add_column("api_keys", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_keys", sa.Column("label", sa.String(length=80), nullable=True))

    op.create_table(
        "auth_nonces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("address", sa.String(length=42), nullable=False),
        sa.Column("message", sa.String(length=2000), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_nonces_nonce", "auth_nonces", ["nonce"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_auth_nonces_nonce", table_name="auth_nonces")
    op.drop_table("auth_nonces")
    op.drop_column("api_keys", "label")
    op.drop_column("api_keys", "expires_at")
    op.drop_index("ix_developers_wallet_address", table_name="developers")
    op.drop_column("developers", "wallet_address")
