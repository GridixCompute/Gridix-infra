"""api_keys.kind — separate wallet sessions from programmatic keys

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-19

Minting a programmatic key requires holding a wallet *session*, and that check needs
something to read. Inferring it from ``expires_at IS NOT NULL`` would tie the guard to a
lifetime policy instead of to how the credential was obtained, so the distinction is
stored outright.

Backfill: the wallet sign-in path has always labelled its keys "session" and always set
an expiry, so those rows are sessions. Everything else is a registration key already
being used from scripts and the agent CLI — programmatic, which is also the default for
rows written between this migration and the deploy that starts setting the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="programmatic"),
    )
    # Reclassify the rows wallet sign-in minted. Both conditions, not just the label: a
    # developer is free to label a programmatic key "session", and only the sign-in path
    # sets an expiry.
    op.execute(
        "UPDATE api_keys SET kind = 'session' "
        "WHERE label = 'session' AND expires_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("api_keys", "kind")
