"""Blob storage abstraction for job input/result payloads.

Blobs never live inline in Postgres. For the MVP they land on a local volume behind a
narrow interface; swapping in an S3-compatible backend is an implementation change, not
an API change. Both the API (uploads/downloads) and the provider agent (fetch input,
upload result) depend only on :class:`Storage`.
"""

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import Settings, get_settings


class Storage(ABC):
    """A content-addressed blob store. ``ref`` values are opaque storage keys."""

    @abstractmethod
    async def put(self, data: bytes, *, suffix: str = "") -> str:
        """Store ``data`` and return its ref."""

    @abstractmethod
    async def get(self, ref: str) -> bytes:
        """Return the bytes stored under ``ref``. Raises ``FileNotFoundError`` if absent."""

    @abstractmethod
    async def exists(self, ref: str) -> bool:
        """Return whether ``ref`` resolves to a stored blob."""


def _content_ref(data: bytes, suffix: str) -> str:
    """Derive a content-addressed ref (sha256) so identical inputs dedupe."""
    digest = hashlib.sha256(data).hexdigest()
    return f"{digest}{suffix}"


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


class S3Storage(Storage):
    """Seam for an S3-compatible backend. Not implemented in the MVP."""

    def __init__(self, settings: Settings) -> None:  # pragma: no cover - seam only
        raise NotImplementedError(
            "S3 storage backend is a post-MVP seam; set GRIDIX_STORAGE_BACKEND=local"
        )

    async def put(self, data: bytes, *, suffix: str = "") -> str:  # pragma: no cover
        raise NotImplementedError

    async def get(self, ref: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    async def exists(self, ref: str) -> bool:  # pragma: no cover
        raise NotImplementedError


_storage: Storage | None = None


def get_storage() -> Storage:
    """Return the configured storage backend (process-wide singleton)."""
    global _storage
    if _storage is None:
        settings = get_settings()
        if settings.storage_backend == "s3":
            _storage = S3Storage(settings)
        else:
            _storage = LocalStorage(settings.storage_local_path)
    return _storage
