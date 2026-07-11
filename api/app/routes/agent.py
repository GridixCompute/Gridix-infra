"""Agent-facing endpoints: poll for work, heartbeat to hold the lease, report status.

These are called by the provider agent (Session 4). Assignment itself is done by the
scheduler; ``poll`` only surfaces work already assigned to the calling provider.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from loguru import logger
from sqlalchemy import select

from app.deps import ProviderDep, SessionDep, SettingsDep
from app.models import AttemptOutcome, Job, JobAttempt, JobStatus, PathType, Provider
from app.paths import NatType, provider_directly_reachable, record_path
from app.presence import is_connected, mark_seen
from app.results import record_result
from app.schemas import (
    Ack,
    AgentJob,
    AgentPathReport,
    AgentPollResponse,
    AgentResultRequest,
    AgentStatusRequest,
    BlobRef,
    HeartbeatRequest,
    HeartbeatResponse,
    PathResponse,
    PingResponse,
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


async def _next_assigned_job(session: SessionDep, provider: Provider) -> Job | None:
    """The oldest job assigned to this provider that it has not yet started."""
    return await session.scalar(
        select(Job)
        .where(
            Job.assigned_provider_id == provider.id,
            Job.status == JobStatus.assigned,
        )
        .order_by(Job.assigned_at.asc())
        .limit(1)
    )


@router.post("/poll", response_model=AgentPollResponse)
async def poll(
    provider: ProviderDep, session: SessionDep, settings: SettingsDep
) -> AgentPollResponse:
    """Long-poll for work: return immediately if a job is assigned, else hold the
    connection open up to ``poll_hold_seconds`` before returning empty.

    Holding the request open keeps the control channel warm across idle periods while
    still surfacing new work within a poll tick of it being assigned.
    """
    mark_seen(provider, _now(), settings.connection_timeout_seconds)
    await session.commit()  # record presence before we begin holding

    deadline = _now() + timedelta(seconds=settings.poll_hold_seconds)
    while True:
        job = await _next_assigned_job(session, provider)
        if job is not None:
            return AgentPollResponse(job=AgentJob.model_validate(job))
        remaining = (deadline - _now()).total_seconds()
        if remaining <= 0:
            return AgentPollResponse(job=None)
        await asyncio.sleep(min(settings.poll_tick_seconds, remaining))
        # End the read transaction so the next query sees newly-assigned work, without
        # expiring loaded ORM objects (which would trigger a sync lazy-load).
        await session.commit()


@router.post("/ping", response_model=PingResponse)
async def ping(provider: ProviderDep, session: SessionDep, settings: SettingsDep) -> PingResponse:
    """Idle keepalive: refresh presence so the coordinator knows the agent is alive."""
    now = _now()
    mark_seen(provider, now, settings.connection_timeout_seconds)
    return PingResponse(
        connected=is_connected(provider, now, settings.connection_timeout_seconds),
        connected_at=provider.connected_at,
        last_seen=provider.last_seen,
    )


@router.post("/path", response_model=PathResponse)
async def report_path(
    body: AgentPathReport,
    provider: ProviderDep,
    session: SessionDep,
    settings: SettingsDep,
) -> PathResponse:
    """Negotiate the reachability path from the agent's NAT report.

    A direct P2P path is chosen when the NAT topology allows it (open / restricted cone);
    a symmetric NAT can't be punched, so the session uses the relay. The choice is
    recorded on the provider and logged. Actual hole punching happens out of band; a
    direct send that fails still falls back to relay transparently (ProviderChannel).
    """
    mark_seen(provider, _now(), settings.connection_timeout_seconds)
    provider_nat = NatType(body.nat_type)
    path = PathType.direct if provider_directly_reachable(provider_nat) else PathType.relay
    record_path(provider, path, _now())
    logger.info(
        "provider {} path → {} (nat={}, {} candidates)",
        provider.id,
        path,
        provider_nat,
        len(body.candidates),
    )
    return PathResponse(path_type=path.value)


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    body: HeartbeatRequest, provider: ProviderDep, session: SessionDep, settings: SettingsDep
) -> HeartbeatResponse:
    """Extend the lease on an in-flight job so the reaper does not reclaim it."""
    job = await _owned_active_job(session, provider, body.job_id)
    if job.status not in (JobStatus.assigned, JobStatus.running):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is not in flight.")
    mark_seen(provider, _now(), settings.connection_timeout_seconds)
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
    job_id: uuid.UUID,
    body: AgentStatusRequest,
    provider: ProviderDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Ack:
    """Agent reports it has begun executing: ``assigned → running``."""
    job = await _owned_active_job(session, provider, job_id)
    mark_seen(provider, _now(), settings.connection_timeout_seconds)
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
