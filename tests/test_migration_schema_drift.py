"""Model↔migration drift gate: the migrated schema must match the model, structurally.

A table, column, index, or constraint can be added to ``models.py`` and used while the matching
Alembic migration is forgotten. The hermetic suite cannot catch this: it builds the schema from
the model via ``Base.metadata.create_all``, so everything is always present under test. A real
deploy runs ``alembic upgrade head`` instead, and anything a migration missed is simply absent —
a ``SELECT`` on a missing table raises ``OperationalError``, and a "unique" a migration made
non-unique silently admits duplicates.

That is exactly what happened twice: ``providers.wallet_address`` (added by 0020) had no
migration and broke provider auth on the first live deploy, and the four ``chain_*`` settlement
tables existed only in the model — latent because chain is off by default, but a broken
``alembic upgrade head`` the moment chain is turned on.

The first version of this gate (0020) was scoped to *columns only* to land green while the
table/index drift was tracked separately. This is the widened version: it fails on a
missing/extra TABLE, COLUMN, INDEX, or CONSTRAINT. Type and server-default comparison stays OFF —
SQLite reflects those loosely, so comparing them produces false positives that are noise, not
drift. This gate is about *presence and shape*, which is where real deploy breakage lives.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine

_REPO = Path(__file__).resolve().parents[1]


def _migrated_schema_diffs():
    """Run migrations on a throwaway DB and diff the result against the model metadata."""
    import app.models  # noqa: F401 - registers every table on Base.metadata
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.db import Base

    db_path = tempfile.mktemp(suffix=".db")
    env = {
        **os.environ,
        "GRIDIX_DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "GRIDIX_ENV": "dev",
        "GRIDIX_SECRET_KEY": "migration-drift-gate-000000000000000000",
        # Force the app under test's package (matches CI's editable install; in a git
        # worktree it overrides the editable install that points at the main checkout).
        "PYTHONPATH": str(_REPO / "api"),
    }
    up = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    assert up.returncode == 0, f"`alembic upgrade head` failed:\n{up.stderr}"

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            # Presence/shape only: comparing types and server defaults on SQLite yields false
            # positives (loose type reflection), which would be noise rather than real drift.
            ctx = MigrationContext.configure(
                conn, opts={"compare_type": False, "compare_server_default": False}
            )
            return compare_metadata(ctx, Base.metadata)
    finally:
        engine.dispose()
        os.unlink(db_path)


def _describe(diff) -> list[str]:
    """Flatten one compare_metadata diff into human-readable drift descriptions."""
    if isinstance(diff, list):  # column-level diffs arrive grouped in a list
        return [line for item in diff for line in _describe(item)]
    op = diff[0]
    if op in ("add_table", "remove_table"):
        return [f"{op}: {diff[1].name}"]
    if op in ("add_column", "remove_column"):
        return [f"{op}: {diff[2]}.{diff[3].name}"]
    if op in ("add_index", "remove_index"):
        idx = diff[1]
        cols = [c.name for c in idx.columns]
        return [f"{op}: {idx.table.name}.{idx.name} unique={bool(idx.unique)} cols={cols}"]
    if op in ("add_constraint", "remove_constraint"):
        con = diff[1]
        table = getattr(getattr(con, "table", None), "name", "?")
        return [f"{op}: {type(con).__name__} {getattr(con, 'name', None)} on {table}"]
    return [f"{op}: {diff[1:]}"]  # any other structural op we did not special-case


def test_migrated_schema_matches_model() -> None:
    problems = sorted(line for diff in _migrated_schema_diffs() for line in _describe(diff))
    assert not problems, (
        "model/migration schema drift (tables, columns, indexes, or constraints present in one "
        "but not the other):\n  " + "\n  ".join(problems) + "\nAdd or fix a migration so the "
        "migrated schema matches models.py (migrations 0021/0022 are the templates)."
    )
