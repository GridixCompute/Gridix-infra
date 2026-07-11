"""Chunked / resumable uploads (Session 8.4).

Large blobs (models, datasets) are uploaded in chunks that append to a staging file by
offset. If the connection drops, the client asks how many bytes were received and resumes
from there instead of restarting. On completion the staged bytes are assembled, verified
against the declared sha256, and promoted into content-addressed storage.

Staging is a local append-only file per upload id. The production S3 path uses multipart
upload (the same offset/resume contract), validated on infra; the offset bookkeeping and
resume logic here are backend-agnostic and fully tested.
"""

import uuid
from pathlib import Path

from app.config import get_settings


class OffsetMismatchError(ValueError):
    """Raised when a chunk's declared offset doesn't match the bytes already received."""

    def __init__(self, expected: int, got: int) -> None:
        super().__init__(f"offset mismatch: expected {expected}, got {got}")
        self.expected = expected
        self.got = got


class ChunkedUploadStaging:
    """Append-by-offset staging for resumable uploads, one file per upload id."""

    def __init__(self, staging_dir: str | None = None) -> None:
        root = staging_dir or f"{get_settings().storage_local_path}/staging"
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, upload_id: uuid.UUID) -> Path:
        return self._root / f"{upload_id}.part"

    def create(self, upload_id: uuid.UUID) -> None:
        """Start a new (empty) staging file."""
        self._path(upload_id).write_bytes(b"")

    def received(self, upload_id: uuid.UUID) -> int:
        """Bytes staged so far (0 if the upload is unknown/empty)."""
        path = self._path(upload_id)
        return path.stat().st_size if path.exists() else 0

    def append(self, upload_id: uuid.UUID, offset: int, chunk: bytes) -> int:
        """Append ``chunk`` at ``offset``; return the new received total.

        Idempotent-safe: the offset must equal the current size, so a duplicated or
        out-of-order chunk is rejected rather than corrupting the stream.
        """
        current = self.received(upload_id)
        if offset != current:
            raise OffsetMismatchError(current, offset)
        with self._path(upload_id).open("ab") as fh:
            fh.write(chunk)
        return current + len(chunk)

    def assemble(self, upload_id: uuid.UUID) -> bytes:
        """Return the fully staged bytes."""
        return self._path(upload_id).read_bytes()

    def cleanup(self, upload_id: uuid.UUID) -> None:
        """Remove the staging file once promoted or aborted."""
        path = self._path(upload_id)
        if path.exists():
            path.unlink()
