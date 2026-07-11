"""Session 8.1 — content-addressed storage over a pluggable object store."""

import pytest
from app.storage import (
    InMemoryObjectStore,
    LocalStorage,
    S3Storage,
    content_digest,
)


@pytest.mark.parametrize("kind", ["local", "s3"])
async def test_put_get_exists_and_content_addressing(kind, tmp_path) -> None:
    store = LocalStorage(str(tmp_path)) if kind == "local" else S3Storage(InMemoryObjectStore())
    data = b"hello gridix" * 10

    ref = await store.put(data)
    assert ref == content_digest(data)  # ref is the sha256 of the content
    assert await store.exists(ref)
    assert await store.get(ref) == data

    # Same content → same digest (dedupe); putting again is idempotent.
    assert await store.put(data) == ref
    # Different content → different digest.
    assert await store.put(b"other") != ref
    # Unknown ref does not exist.
    assert not await store.exists(content_digest(b"never stored"))


async def test_s3_backend_uses_prefixed_keys() -> None:
    backing = InMemoryObjectStore()
    store = S3Storage(backing, prefix="blobs/")
    ref = await store.put(b"payload")
    assert await backing.head_object(f"blobs/{ref}")
