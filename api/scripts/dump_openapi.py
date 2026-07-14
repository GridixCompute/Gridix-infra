"""Dump the FastAPI OpenAPI schema to frontend/openapi.snapshot.json.

The frontend generates its TypeScript types from this snapshot, so it is the
single source of truth for the API contract. CI regenerates it and fails if the
committed snapshot (or the generated types) drift from the live schema.

Run from anywhere with the backend importable:
    GRIDIX_ENV=dev GRIDIX_STORAGE_LOCAL_PATH=/tmp/blobs python api/scripts/dump_openapi.py
"""

import json
import os
import pathlib

# The app creates a local blob-staging dir on import; keep it off the real path.
os.environ.setdefault("GRIDIX_ENV", "dev")
os.environ.setdefault("GRIDIX_STORAGE_LOCAL_PATH", "/tmp/gridix-openapi-blobs")

from app.main import app  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "openapi.snapshot.json"


def main() -> None:
    schema = app.openapi()
    OUT.write_text(json.dumps(schema, indent=2))
    print(f"wrote {OUT} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    main()
