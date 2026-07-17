"""Model↔migration drift gate: no model column may be missing from the migrated schema.

A column can be added to a model in ``models.py`` and used in queries while the matching
Alembic migration is forgotten. The hermetic suite cannot catch this: it builds the schema
from the model via ``Base.metadata.create_all``, so the column is always present in tests.
A real deploy runs ``alembic upgrade head`` instead, and a column that no migration created
makes every ``SELECT`` on that table raise ``OperationalError``. That is exactly how
``providers.wallet_address`` (added by migration 0020) silently blocked provider auth and
dispatch on the first live deploy — green tests, broken deploy.

This gate runs the migrations on a fresh database and asserts that autogenerate finds no
column that is present in the model but absent from the migrated schema.

Scope is deliberately *columns only*. Whole missing tables and index-uniqueness drift are a
separate, still-open concern (the ``chain_*`` settlement tables in ``models.py`` have no
migration yet) and would make this gate fail for a different class of bug that this PR does
not fix. Keeping the scope tight means this gate stays green until a new missing *column*
is introduced — which is precisely the regression it exists to catch.
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
            ctx = MigrationContext.configure(conn)
            return compare_metadata(ctx, Base.metadata)
    finally:
        engine.dispose()
        os.unlink(db_path)


def test_no_model_column_missing_from_migrations() -> None:
    diffs = _migrated_schema_diffs()
    missing = [d for d in diffs if isinstance(d, tuple) and d and d[0] == "add_column"]
    detail = [f"{d[2]}.{d[3].name}" for d in missing]
    assert not missing, (
        f"model columns absent from the migrated schema: {detail}. "
        "Every column in models.py needs a migration that creates it — add one "
        "(migration 0020 is the template, for providers.wallet_address)."
    )
