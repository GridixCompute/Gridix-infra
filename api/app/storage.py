"""Blob storage — content-addressed, local or S3-backed.

Blobs never live inline in Postgres. Every backend is *content-addressed*: the ref is the
sha256 of the bytes, so identical content dedupes and the ref is self-verifying
(Session 8.2). Both the API and the provider agent depend only on :class:`Storage`.

Local (a mounted volume) is the default; the S3 backend delegates to a pluggable
:class:`ObjectStore` so it can run against real object storage in production and an
in-memory store in tests.
"""

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

from app.config import Settings, get_settings


def content_digest(data: bytes) -> str:
    """Return the sha256 hex digest used as the content-addressed ref."""
    return hashlib.sha256(data).hexdigest()


def _content_ref(data: bytes, suffix: str) -> str:
    return f"{content_digest(data)}{suffix}"


class Storage(ABC):
    """A content-addressed blob store. ``ref`` values are opaque storage keys."""

    @abstractmethod
    async def put(self, data: bytes, *, suffix: str = "") -> str:
        """Store ``data`` and return its content-addressed ref."""

    @abstractmethod
    async def get(self, ref: str) -> bytes:
        """Return the bytes stored under ``ref`` (raises if absent)."""

    @abstractmethod
    async def exists(self, ref: str) -> bool:
        """Return whether ``ref`` resolves to a stored blob."""


class LocalStorage(Storage):
    """Filesystem-backed store rooted at a local directory (a mounted volume in prod)."""

    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, ref: str) -> Path:
        # Refs are sha256 hex (+ optional suffix); reject traversal defensively.
        if "/" in ref or "\\" in ref or ".." in ref:
            raise ValueError(f"invalid blob ref: {ref!r}")
        return self._root / ref

    async def put(self, data: bytes, *, suffix: str = "") -> str:
        ref = _content_ref(data, suffix)
        path = self._path(ref)
        if not path.exists():
            path.write_bytes(data)
        return ref

    async def get(self, ref: str) -> bytes:
        return self._path(ref).read_bytes()

    async def exists(self, ref: str) -> bool:
        return self._path(ref).exists()


class ObjectStore(Protocol):
    """A minimal key→bytes object store (the part of S3 we use)."""

    async def put_object(self, key: str, data: bytes) -> None: ...
    async def get_object(self, key: str) -> bytes: ...
    async def head_object(self, key: str) -> bool: ...


class InMemoryObjectStore:
    """An in-process object store — a valid backend and the test double for S3."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def put_object(self, key: str, data: bytes) -> None:
        self._objects[key] = data

    async def get_object(self, key: str) -> bytes:
        if key not in self._objects:
            raise FileNotFoundError(key)
        return self._objects[key]

    async def head_object(self, key: str) -> bool:
        return key in self._objects


class S3ObjectStore:  # pragma: no cover - requires real object storage
    """S3-compatible object store via aioboto3 (validated on infra)."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.s3_bucket
        self._endpoint = settings.s3_endpoint_url or None

    def _session(self):
        import aioboto3  # lazy: only needed when the S3 backend is active

        return aioboto3.Session()

    async def put_object(self, key: str, data: bytes) -> None:
        async with self._session().client("s3", endpoint_url=self._endpoint) as s3:
            await s3.put_object(Bucket=self._bucket, Key=key, Body=data)

    async def get_object(self, key: str) -> bytes:
        async with self._session().client("s3", endpoint_url=self._endpoint) as s3:
            resp = await s3.get_object(Bucket=self._bucket, Key=key)
            async with resp["Body"] as body:
                return await body.read()

    async def head_object(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        async with self._session().client("s3", endpoint_url=self._endpoint) as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
                return True
            except ClientError:
                return False


class S3Storage(Storage):
    """Content-addressed store backed by any :class:`ObjectStore`."""

    def __init__(self, store: ObjectStore, prefix: str = "blobs/") -> None:
        self._store = store
        self._prefix = prefix

    def _key(self, ref: str) -> str:
        return f"{self._prefix}{ref}"

    async def put(self, data: bytes, *, suffix: str = "") -> str:
        ref = _content_ref(data, suffix)
        if not await self._store.head_object(self._key(ref)):
            await self._store.put_object(self._key(ref), data)
        return ref

    async def get(self, ref: str) -> bytes:
        return await self._store.get_object(self._key(ref))

    async def exists(self, ref: str) -> bool:
        return await self._store.head_object(self._key(ref))


_storage: Storage | None = None


def get_storage() -> Storage:
    """Return the configured storage backend (process-wide singleton)."""
    global _storage
    if _storage is None:
        settings = get_settings()
        if settings.storage_backend == "s3":
            _storage = S3Storage(S3ObjectStore(settings))
        else:
            _storage = LocalStorage(settings.storage_local_path)
    return _storage


def set_storage(storage: Storage) -> None:
    """Install a storage backend (used by tests and for backend swaps)."""
    global _storage
    _storage = storage
