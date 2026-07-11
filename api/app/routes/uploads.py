"""Resumable chunked upload endpoints (Session 8.4).

Flow: POST /uploads → PATCH /uploads/{id} (append chunks by offset) → POST
/uploads/{id}/complete. If the connection drops, GET /uploads/{id} returns how many bytes
were received so the client resumes from that offset instead of restarting.
"""

import uuid

from fastapi import APIRouter, Header, HTTPException, Request, status
from loguru import logger

from app.chunked import ChunkedUploadStaging, OffsetMismatchError
from app.deps import DeveloperDep, SessionDep
from app.models import UploadSession
from app.schemas import BlobRef, UploadCreateRequest, UploadSessionResponse
from app.storage import IntegrityError, get_storage, verify_integrity

router = APIRouter(tags=["uploads"])
_staging = ChunkedUploadStaging()

# Cap a single chunk so one request can't exhaust memory (tune per deployment).
_MAX_CHUNK_BYTES = 64 * 1024 * 1024


async def _owned_session(session: SessionDep, developer_id: uuid.UUID, upload_id: uuid.UUID):
    upload = await session.get(UploadSession, upload_id)
    if upload is None or upload.developer_id != developer_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found.")
    return upload


@router.post("/uploads", response_model=UploadSessionResponse, status_code=201)
async def create_upload(
    body: UploadCreateRequest, developer: DeveloperDep, session: SessionDep
) -> UploadSessionResponse:
    """Begin a resumable upload."""
    upload = UploadSession(developer_id=developer.id, declared_digest=body.digest)
    session.add(upload)
    await session.flush()
    _staging.create(upload.id)
    return UploadSessionResponse(upload_id=upload.id, received=0)


@router.get("/uploads/{upload_id}", response_model=UploadSessionResponse)
async def get_upload(
    upload_id: uuid.UUID, developer: DeveloperDep, session: SessionDep
) -> UploadSessionResponse:
    """Return the current offset (bytes received) so the client can resume."""
    upload = await _owned_session(session, developer.id, upload_id)
    return UploadSessionResponse(
        upload_id=upload.id, received=_staging.received(upload.id), blob_ref=upload.blob_ref
    )


@router.patch("/uploads/{upload_id}", response_model=UploadSessionResponse)
async def append_chunk(
    upload_id: uuid.UUID,
    request: Request,
    developer: DeveloperDep,
    session: SessionDep,
    upload_offset: int = Header(alias="Upload-Offset"),
) -> UploadSessionResponse:
    """Append a chunk at ``Upload-Offset``. A mismatched offset is a 409 (retry after GET)."""
    upload = await _owned_session(session, developer.id, upload_id)
    if upload.blob_ref is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Upload already completed."
        )
    chunk = await request.body()
    if len(chunk) > _MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail=f"Chunk exceeds {_MAX_CHUNK_BYTES} bytes.")
    try:
        received = _staging.append(upload.id, upload_offset, chunk)
    except OffsetMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Offset mismatch: resume from {exc.expected}.",
        ) from exc
    return UploadSessionResponse(upload_id=upload.id, received=received)


@router.post("/uploads/{upload_id}/complete", response_model=BlobRef)
async def complete_upload(
    upload_id: uuid.UUID, developer: DeveloperDep, session: SessionDep
) -> BlobRef:
    """Assemble the staged chunks, verify the declared digest, and promote to a blob."""
    upload = await _owned_session(session, developer.id, upload_id)
    if upload.blob_ref is not None:
        data = await get_storage().get(upload.blob_ref)
        return BlobRef(ref=upload.blob_ref, size=len(data))

    data = _staging.assemble(upload.id)
    ref = await get_storage().put(data)
    if upload.declared_digest is not None:
        try:
            verify_integrity(upload.declared_digest, data)
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Assembled bytes do not match digest.",
            ) from exc

    upload.blob_ref = ref
    _staging.cleanup(upload.id)
    logger.info("upload {} completed → blob {} ({} bytes)", upload.id, ref, len(data))
    return BlobRef(ref=ref, size=len(data))
