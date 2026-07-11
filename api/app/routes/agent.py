"""Agent-facing endpoints: poll for work, heartbeat to hold the lease, report status.

These are called by the provider agent (Session 4). Assignment itself is done by the
scheduler; ``poll`` only surfaces work already assigned to the calling provider.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from loguru import logger
from sqlalchemy import select

from app.deps import ProviderDep, SessionDep, SettingsDep
from app.models import AttemptOutcome, Job, JobAttempt, JobStatus, Provider
from app.results import record_result
from app.schemas import (
    Ack,
    AgentJob,
    AgentPollResponse,
    AgentResultRequest,
    AgentStatusRequest,
    BlobRef,
    HeartbeatRequest,
    HeartbeatResponse,
)
from app.state_machine import IllegalTransitionError, transition
from app.storage import get_storage

router = APIRouter(prefix="/agent", tags=["agent"])

# Guardrail on result blob size, mirroring the developer upload path.
_MAX_BLOB_BYTES = 256 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(UTC)


async def _owned_active_job(session: SessionDep, provider: Provider, job_id: uuid.UUID) -> Job:
    """Load a job that is currently assigned to this provider, or 404."""
    job = await session.get(Job, job_id)
    if job is None or job.assigned_provider_id != provider.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job


@router.post("/poll", response_model=AgentPollResponse)
async def poll(provider: ProviderDep, session: SessionDep) -> AgentPollResponse:
    """Return the oldest job assigned to this provider that it has not yet started."""
    job = await session.scalar(
        select(Job)
        .where(
            Job.assigned_provider_id == provider.id,
            Job.status == JobStatus.assigned,
        )
        .order_by(Job.assigned_at.asc())
        .limit(1)
    )
    if job is None:
        return AgentPollResponse(job=None)
    return AgentPollResponse(job=AgentJob.model_validate(job))


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    body: HeartbeatRequest, provider: ProviderDep, session: SessionDep, settings: SettingsDep
) -> HeartbeatResponse:
    """Extend the lease on an in-flight job so the reaper does not reclaim it."""
    job = await _owned_active_job(session, provider, body.job_id)
    if job.status not in (JobStatus.assigned, JobStatus.running):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is not in flight.")
    lease = _now() + timedelta(seconds=settings.lease_seconds)
    job.lease_expires_at = lease
    # Keep the current attempt's lease in sync.
    attempt = await session.scalar(
        select(JobAttempt)
        .where(JobAttempt.job_id == job.id)
        .order_by(JobAttempt.attempt_number.desc())
        .limit(1)
    )
    if attempt is not None:
        attempt.lease_expires_at = lease
    return HeartbeatResponse(job_id=job.id, lease_expires_at=lease)


@router.post("/jobs/{job_id}/status", response_model=Ack)
async def report_status(
    job_id: uuid.UUID, body: AgentStatusRequest, provider: ProviderDep, session: SessionDep
) -> Ack:
    """Agent reports it has begun executing: ``assigned → running``."""
    job = await _owned_active_job(session, provider, job_id)
    try:
        transition(job, JobStatus.running)
    except IllegalTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    attempt = await session.scalar(
        select(JobAttempt)
        .where(JobAttempt.job_id == job.id)
        .order_by(JobAttempt.attempt_number.desc())
        .limit(1)
    )
    if attempt is not None:
        attempt.outcome = AttemptOutcome.running
        attempt.started_at = _now()
    logger.info("job {} reported running by provider {}", job.id, provider.id)
    return Ack(job_id=job.id, status=job.status)


@router.get("/jobs/{job_id}/input")
async def download_input(job_id: uuid.UUID, provider: ProviderDep, session: SessionDep) -> Response:
    """Stream the input blob for a job assigned to this provider."""
    job = await _owned_active_job(session, provider, job_id)
    if job.input_ref is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    data = await get_storage().get(job.input_ref)
    return Response(content=data, media_type="application/octet-stream")


@router.post("/blobs", response_model=BlobRef, status_code=status.HTTP_201_CREATED)
async def upload_result_blob(file: UploadFile, provider: ProviderDep) -> BlobRef:
    """Store a result blob and return its (content-addressed) ref for the result call."""
    data = await file.read()
    if len(data) > _MAX_BLOB_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Blob exceeds {_MAX_BLOB_BYTES} bytes.",
        )
    ref = await get_storage().put(data)
    return BlobRef(ref=ref, size=len(data))


@router.post("/jobs/{job_id}/result", response_model=Ack)
async def submit_result(
    job_id: uuid.UUID,
    body: AgentResultRequest,
    provider: ProviderDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Ack:
    """Accept a result + proof and move the job to its terminal state.

    The result is verified (proof, exit/timeout, canary match) and, once enough attempts
    are in, the job finalizes by quorum — settling the winner and slashing cheats.
    """
    job = await _owned_active_job(session, provider, job_id)
    if job.status not in (JobStatus.assigned, JobStatus.running):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is not in flight.")
    # The proof's output hash must match the content-addressed ref we stored.
    if body.result_ref is not None:
        claimed = body.proof.get("output_sha256")
        if claimed is not None and not body.result_ref.startswith(claimed):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="proof.output_sha256 does not match result_ref.",
            )
    final = await record_result(session, job, provider, body, settings)
    return Ack(job_id=job.id, status=final)
