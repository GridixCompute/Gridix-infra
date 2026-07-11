"""Agent-facing endpoints: poll for work, heartbeat to hold the lease, report status.

These are called by the provider agent (Session 4). Assignment itself is done by the
scheduler; ``poll`` only surfaces work already assigned to the calling provider.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from loguru import logger
from sqlalchemy import delete, select

from app.attestation import verify_attestation
from app.bandwidth import record_bandwidth
from app.benchmark import validate_benchmark
from app.deps import ProviderDep, SessionDep, SettingsDep
from app.health import evaluate_degraded
from app.key_broker import KeyReleaseError, release_data_key
from app.models import (
    AttemptOutcome,
    BandwidthDirection,
    BenchmarkReport,
    HealthSample,
    Job,
    JobAttempt,
    JobStatus,
    PathType,
    Provider,
    ProviderArtifact,
)
from app.paths import NatType, provider_directly_reachable, record_path
from app.peer_distribution import plan_fetch, seeders_for
from app.presence import is_connected, mark_seen
from app.results import record_result
from app.schemas import (
    Ack,
    AgentJob,
    AgentPathReport,
    AgentPollResponse,
    AgentResultRequest,
    AgentStatusRequest,
    AttestationQuote,
    AttestationResult,
    BenchmarkResponse,
    BenchmarkSubmit,
    BlobRef,
    CacheReport,
    DataKeyResponse,
    HealthReport,
    HealthResult,
    HeartbeatRequest,
    HeartbeatResponse,
    JobSecretsResponse,
    PathResponse,
    PeerFetchPlan,
    PingResponse,
)
from app.secrets_broker import SecretReleaseError, mint_job_secrets
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


@router.post("/cache", status_code=status.HTTP_204_NO_CONTENT)
async def report_cache(
    body: CacheReport, provider: ProviderDep, session: SessionDep, settings: SettingsDep
) -> Response:
    """Sync the provider's cached artifact digests (Session 8.5 locality hint).

    Replaces the recorded set so it tracks the agent's LRU cache; the scheduler then
    soft-prefers this provider for jobs whose input it already holds.
    """
    mark_seen(provider, _now(), settings.connection_timeout_seconds)
    await session.execute(
        delete(ProviderArtifact).where(ProviderArtifact.provider_id == provider.id)
    )
    seen: set[str] = set()
    for digest in body.cached:
        if digest and digest not in seen:
            seen.add(digest)
            session.add(ProviderArtifact(provider_id=provider.id, digest=digest))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/artifacts/{digest}/peers", response_model=PeerFetchPlan)
async def artifact_peers(
    digest: str, provider: ProviderDep, session: SessionDep, settings: SettingsDep
) -> PeerFetchPlan:
    """Return where to fetch an artifact from (Session 8.7). Origin unless peer
    distribution is enabled and another provider already seeds the digest."""
    plan = await plan_fetch(session, provider.id, digest, settings)
    seeders = (
        await seeders_for(session, digest, exclude=provider.id)
        if settings.peer_distribution_enabled
        else []
    )
    return PeerFetchPlan(
        enabled=settings.peer_distribution_enabled,
        kind=plan.kind,
        provider_id=plan.provider_id,
        seeders=seeders,
    )


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


@router.post("/benchmark", response_model=BenchmarkResponse, status_code=201)
async def submit_benchmark(
    body: BenchmarkSubmit, provider: ProviderDep, session: SessionDep, settings: SettingsDep
) -> BenchmarkReport:
    """Store a signed onboarding benchmark and validate it against declared hardware.

    The report is attributed to the authenticated provider; validation (Session 11.2)
    catches a machine claiming hardware it can't benchmark to.
    """
    mark_seen(provider, _now(), settings.connection_timeout_seconds)
    ok, reason = validate_benchmark(body.metrics, provider.gpu_model)
    report = BenchmarkReport(
        provider_id=provider.id, metrics=body.metrics, signature=body.signature, validated=ok
    )
    session.add(report)
    await session.flush()
    if not ok:
        # A provider whose benchmark contradicts its claims is down-tiered (disabled).
        provider.enabled = False
        logger.warning("provider {} benchmark rejected: {}", provider.id, reason)
    return report


@router.post("/health", response_model=HealthResult)
async def report_health(
    body: HealthReport, provider: ProviderDep, session: SessionDep, settings: SettingsDep
) -> HealthResult:
    """Ingest a telemetry sample and flag the provider degraded if a signal crosses a
    threshold (Session 11.4). Recovery telemetry clears the flag."""
    mark_seen(provider, _now(), settings.connection_timeout_seconds)
    session.add(
        HealthSample(
            provider_id=provider.id,
            gpu_temp_c=body.gpu_temp_c,
            throttling=body.throttling,
            error_rate=body.error_rate,
            latency_ms=body.latency_ms,
        )
    )
    degraded, reason = evaluate_degraded(body.model_dump(), settings)
    provider.degraded = degraded
    if degraded:
        logger.warning("provider {} degraded: {}", provider.id, reason)
    return HealthResult(degraded=degraded, reason=reason)


@router.post("/attest", response_model=AttestationResult)
async def submit_attestation(
    body: AttestationQuote, provider: ProviderDep, session: SessionDep, settings: SettingsDep
) -> AttestationResult:
    """Verify a TEE attestation quote and set the provider's attested flag (Session 9.5).

    A valid quote grants ``tee_attested`` (enabling confidential-tee assignment and key
    release); a tampered or absent quote clears it and is rejected (400).
    """
    mark_seen(provider, _now(), settings.connection_timeout_seconds)
    attested = verify_attestation(body.model_dump(), settings)
    provider.tee_attested = attested
    if not attested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Attestation verification failed."
        )
    logger.info("provider {} attested (measurement={})", provider.id, body.measurement)
    return AttestationResult(attested=True)


@router.get("/jobs/{job_id}/key", response_model=DataKeyResponse)
async def get_job_key(
    job_id: uuid.UUID, provider: ProviderDep, session: SessionDep, settings: SettingsDep
) -> DataKeyResponse:
    """Release the job's data key to its assigned agent (Session 9.3).

    Only the provider the job is assigned to receives it, and only while the job is in
    flight — the key is job-scoped and expires with the job.
    """
    job = await _owned_active_job(session, provider, job_id)
    try:
        dek = release_data_key(job, provider, settings)
    except KeyReleaseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return DataKeyResponse(data_key=dek)


@router.get("/jobs/{job_id}/secrets", response_model=JobSecretsResponse)
async def get_job_secrets(
    job_id: uuid.UUID, provider: ProviderDep, session: SessionDep, settings: SettingsDep
) -> JobSecretsResponse:
    """Mint short-lived, job-scoped secrets for the assigned agent (Session 9.6).

    Values are never persisted and never logged (only their names); they expire on their
    own and are unavailable once the job ends.
    """
    job = await _owned_active_job(session, provider, job_id)
    try:
        secrets, expires_at = mint_job_secrets(job, settings)
    except SecretReleaseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    logger.info("released {} secrets for job {} to provider {}", len(secrets), job.id, provider.id)
    return JobSecretsResponse(secrets=secrets, expires_at=expires_at)


@router.get("/jobs/{job_id}/input")
async def download_input(job_id: uuid.UUID, provider: ProviderDep, session: SessionDep) -> Response:
    """Stream the input blob for a job assigned to this provider."""
    job = await _owned_active_job(session, provider, job_id)
    if job.input_ref is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    data = await get_storage().get(job.input_ref)
    # Downloading input is ingress from the provider's perspective (Session 7.7).
    await record_bandwidth(
        session, provider.id, BandwidthDirection.ingress, len(data), job_id=job.id
    )
    return Response(content=data, media_type="application/octet-stream")


@router.post("/blobs", response_model=BlobRef, status_code=status.HTTP_201_CREATED)
async def upload_result_blob(
    file: UploadFile, provider: ProviderDep, session: SessionDep
) -> BlobRef:
    """Store a result blob and return its (content-addressed) ref for the result call."""
    data = await file.read()
    if len(data) > _MAX_BLOB_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Blob exceeds {_MAX_BLOB_BYTES} bytes.",
        )
    ref = await get_storage().put(data)
    # Uploading a result is egress from the provider's perspective (Session 7.7).
    await record_bandwidth(session, provider.id, BandwidthDirection.egress, len(data))
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
