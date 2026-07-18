"""reconcile two indexes the migrations built differently from the model

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-18

The widened drift gate surfaced two index mismatches, both where a migration enforced (or
failed to enforce) uniqueness differently from what the model declares:

* ``api_keys.key_hash`` — the model declares ``unique=True, index=True`` (a unique index), but
  0001 created a plain, NON-unique index. The deployed schema therefore did not enforce the
  key-hash uniqueness the model promises. This is the material one: correct it to a unique index.

* ``audit_log.seq`` — the model declares a single unique index, but 0016 enforced uniqueness via
  a named ``UniqueConstraint`` (uq_audit_seq) plus a redundant non-unique index. Uniqueness held,
  but via different objects than the model. Reconcile to the model's single unique index.

Corrective, not additive: it drops and recreates indexes (and, on audit_log, a constraint) to
match the model. Index swaps run directly; dropping a constraint needs batch mode on SQLite
(table rebuild) and is a plain ALTER on Postgres.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    with op.batch_alter_table("audit_log", schema=None) as batch:
        batch.drop_constraint("uq_audit_seq", type_="unique")
        batch.drop_index("ix_audit_log_seq")
        batch.create_index("ix_audit_log_seq", ["seq"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("audit_log", schema=None) as batch:
        batch.drop_index("ix_audit_log_seq")
        batch.create_index("ix_audit_log_seq", ["seq"], unique=False)
        batch.create_unique_constraint("uq_audit_seq", ["seq"])

    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=False)
