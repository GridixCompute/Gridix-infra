"""Blob upload endpoint — developers stage job input before submitting."""

from fastapi import APIRouter, HTTPException, UploadFile, status

from app.deps import DeveloperDep
from app.schemas import BlobRef
from app.storage import get_storage

router = APIRouter(tags=["blobs"])

# Guardrail so a single upload can't exhaust the volume (tune per deployment).
_MAX_BLOB_BYTES = 256 * 1024 * 1024


@router.post("/blobs", response_model=BlobRef, status_code=status.HTTP_201_CREATED)
async def upload_blob(file: UploadFile, developer: DeveloperDep) -> BlobRef:
    """Store an input blob and return its ref for use as a job's ``input_ref``."""
    data = await file.read()
    if len(data) > _MAX_BLOB_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Blob exceeds {_MAX_BLOB_BYTES} bytes.",
        )
    ref = await get_storage().put(data)
    return BlobRef(ref=ref, size=len(data))
