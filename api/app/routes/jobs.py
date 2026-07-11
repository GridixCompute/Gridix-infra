"""Developer-facing job endpoints: submit, list, read, download result."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from loguru import logger
from sqlalchemy import select

from app.deps import DeveloperDep, SessionDep, SettingsDep
from app.models import Job, JobAttempt, JobStatus, LedgerEntry
from app.payments import get_payment_provider
from app.pricing import escrow_estimate
from app.redis_client import enqueue_job
from app.schemas import (
    AttemptRecord,
    JobAudit,
    JobResponse,
    LedgerRecord,
    SubmitJobRequest,
)
from app.storage import get_storage

router = APIRouter(tags=["jobs"])


async def _get_owned_job(session: SessionDep, developer_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    """Load a job and assert the caller owns it (404 otherwise — no existence leak)."""
    job = await session.get(Job, job_id)
    if job is None or job.developer_id != developer_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def submit_job(
    body: SubmitJobRequest,
    developer: DeveloperDep,
    session: SessionDep,
    settings: SettingsDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    """Validate, escrow funds for, and enqueue a job.

    The job lands in ``queued`` and its id goes on the queue; the scheduler (Session 3)
    matches it to a provider. Worst-case cost is escrowed now and reconciled at
    settlement. Re-submitting with the same ``Idempotency-Key`` returns the original job
    instead of creating a duplicate.
    """
    # A GPU request must declare vram; a declared input_ref must actually exist.
    if body.resource_spec.gpu and body.resource_spec.gpu_vram_mb <= 0:
        raise HTTPException(
            status_code=422,
            detail="gpu=true requires gpu_vram_mb > 0.",
        )
    if body.input_ref is not None and not await get_storage().exists(body.input_ref):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="input_ref does not resolve to a stored blob.",
        )

    if idempotency_key is not None:
        existing = await session.scalar(
            select(Job).where(
                Job.developer_id == developer.id, Job.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing

    escrow = escrow_estimate(body.resource_spec.model_dump(), body.timeout_seconds, settings)
    job = Job(
        developer_id=developer.id,
        status=JobStatus.queued,
        image_ref=body.image_ref,
        input_ref=body.input_ref,
        resource_spec=body.resource_spec.model_dump(),
        args=body.args.model_dump() if body.args else None,
        allow_egress=body.allow_egress,
        timeout_seconds=body.timeout_seconds,
        is_high_value=body.is_high_value,
        redundancy=body.redundancy,
        exposed_port=body.exposed_port,
        data_tier=body.data_tier,
        wrapped_key=body.wrapped_key,
        idempotency_key=idempotency_key,
        escrow_amount=escrow,
    )
    session.add(job)
    await session.flush()  # assign job.id
    job.queued_at = job.created_at
    await get_payment_provider().hold_escrow(session, job.id, developer.id, escrow)

    # Commit before enqueue so the scheduler never dequeues an id it can't yet read.
    # The DB is the source of truth: if Redis is down, the job is still persisted as
    # `queued` and the scheduler's recovery sweep re-enqueues it (Session 12.5). Escrow was
    # held exactly once above, so a missed enqueue never double-charges.
    await session.commit()
    try:
        await enqueue_job(str(job.id))
    except Exception as exc:  # noqa: BLE001 - degrade gracefully; recovery re-enqueues
        logger.warning("enqueue failed for job {} (will be recovered): {}", job.id, exc)
    logger.info("job {} submitted by developer {} (escrow {})", job.id, developer.id, escrow)
    return job


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(
    developer: DeveloperDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Job]:
    """List the caller's own jobs, newest first."""
    result = await session.scalars(
        select(Job)
        .where(Job.developer_id == developer.id)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, developer: DeveloperDep, session: SessionDep) -> Job:
    """Read one of the caller's own jobs."""
    return await _get_owned_job(session, developer.id, job_id)


@router.get("/jobs/{job_id}/result")
async def download_result(
    job_id: uuid.UUID, developer: DeveloperDep, session: SessionDep
) -> Response:
    """Stream the result blob of a completed job the caller owns."""
    job = await _get_owned_job(session, developer.id, job_id)
    if job.result_ref is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job has no result yet.")
    data = await get_storage().get(job.result_ref)
    return Response(content=data, media_type="application/octet-stream")


@router.get("/jobs/{job_id}/audit", response_model=JobAudit)
async def job_audit(job_id: uuid.UUID, developer: DeveloperDep, session: SessionDep) -> JobAudit:
    """Return the full audit trail for a job: attempts and ledger movements."""
    job = await _get_owned_job(session, developer.id, job_id)
    attempts = list(
        await session.scalars(
            select(JobAttempt)
            .where(JobAttempt.job_id == job.id)
            .order_by(JobAttempt.attempt_number.asc())
        )
    )
    ledger = list(
        await session.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.job_id == job.id)
            .order_by(LedgerEntry.created_at.asc())
        )
    )
    return JobAudit(
        job=JobResponse.model_validate(job),
        attempts=[AttemptRecord.model_validate(a) for a in attempts],
        ledger=[LedgerRecord.model_validate(entry) for entry in ledger],
    )
