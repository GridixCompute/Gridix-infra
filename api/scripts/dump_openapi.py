"""Dump the FastAPI OpenAPI schema to frontend/openapi.snapshot.json.

The frontend generates its TypeScript types from this snapshot, so it is the
single source of truth for the API contract. CI regenerates it and fails if the
committed snapshot (or the generated types) drift from the live schema.

Run from the repo root, with this checkout's backend on the path:
    PYTHONPATH=api python api/scripts/dump_openapi.py

PYTHONPATH is not optional, and the guard below explains why.
"""

import json
import os
import pathlib

# The app creates a local blob-staging dir on import; keep it off the real path.
os.environ.setdefault("GRIDIX_ENV", "dev")
os.environ.setdefault("GRIDIX_STORAGE_LOCAL_PATH", "/tmp/gridix-openapi-blobs")

import app as _app_package  # noqa: E402

_REPO = pathlib.Path(__file__).resolve().parents[2]
_APP_SOURCE = pathlib.Path(_app_package.__file__).resolve()

# Where we WRITE comes from __file__, so it is always this checkout. Where we READ comes
# from sys.path, so an editable install can silently point at a different one. When those
# disagree, this script dumps another checkout's API into this checkout's snapshot and exits
# 0 — no error, no warning, a confident wrong answer. That is exactly what happened with a
# second worktree present: 42 paths written, /v1 nowhere, drift "resolved" backwards.
if _REPO not in _APP_SOURCE.parents:
    raise SystemExit(
        f"app resolved to {_APP_SOURCE}, outside {_REPO}.\n"
        f"This would dump another checkout's API and write a confident, wrong snapshot.\n"
        f"Run with PYTHONPATH=api from the repo root."
    )

from app.main import app  # noqa: E402

OUT = _REPO / "frontend" / "openapi.snapshot.json"


def main() -> None:
    schema = app.openapi()
    OUT.write_text(json.dumps(schema, indent=2))
    print(f"wrote {OUT} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    main()
