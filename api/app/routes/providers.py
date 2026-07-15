"""Provider self-service endpoints: declare capabilities, read back state, bandwidth."""

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.bandwidth import provider_bandwidth
from app.benchmark import trust_source
from app.deps import ProviderDep, SessionDep
from app.models import BenchmarkReport, Job, JobAttempt, ReputationEvent
from app.schemas import (
    BandwidthResponse,
    BenchmarkResponse,
    ProviderCapabilities,
    ProviderJobAttempt,
    ProviderResponse,
    ReputationEventResponse,
)

router = APIRouter(tags=["providers"])


@router.get("/providers/me", response_model=ProviderResponse)
async def get_me(provider: ProviderDep):
    """Return the authenticated provider's current record."""
    return provider


@router.patch("/providers/me", response_model=ProviderResponse)
async def update_me(body: ProviderCapabilities, provider: ProviderDep, session: SessionDep):
    """Partially update declared capabilities. Only provided fields change."""
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(provider, field, value)
    session.add(provider)
    return provider


@router.get("/providers/me/bandwidth", response_model=BandwidthResponse)
async def my_bandwidth(provider: ProviderDep, session: SessionDep) -> BandwidthResponse:
    """Return this provider's byte counters — lifetime and for the current session."""
    lifetime = await provider_bandwidth(session, provider.id)
    session_bw = await provider_bandwidth(session, provider.id, since=provider.connected_at)
    return BandwidthResponse(
        ingress_bytes=lifetime["ingress"],
        egress_bytes=lifetime["egress"],
        total_bytes=lifetime["total"],
        session_ingress_bytes=session_bw["ingress"],
        session_egress_bytes=session_bw["egress"],
    )


@router.get("/providers/me/benchmark", response_model=BenchmarkResponse | None)
async def my_benchmark(provider: ProviderDep, session: SessionDep) -> BenchmarkReport | None:
    """Return the provider's latest benchmark report, or null if none submitted."""
    return await session.scalar(
        select(BenchmarkReport)
        .where(BenchmarkReport.provider_id == provider.id)
        .order_by(BenchmarkReport.created_at.desc())
        .limit(1)
    )


@router.get("/providers/me/jobs", response_model=list[ProviderJobAttempt])
async def my_jobs(
    provider: ProviderDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ProviderJobAttempt]:
    """Return this provider's execution history — one row per attempt, newest first."""
    rows = await session.execute(
        select(JobAttempt, Job)
        .join(Job, JobAttempt.job_id == Job.id)
        .where(JobAttempt.provider_id == provider.id)
        .order_by(JobAttempt.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        ProviderJobAttempt(
            attempt_id=attempt.id,
            job_id=attempt.job_id,
            attempt_number=attempt.attempt_number,
            outcome=str(attempt.outcome),
            job_status=job.status,
            image_ref=job.image_ref,
            is_high_value=job.is_high_value,
            redundancy=job.redundancy,
            created_at=attempt.created_at,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            duration_seconds=(
                (attempt.finished_at - attempt.started_at).total_seconds()
                if attempt.started_at and attempt.finished_at
                else None
            ),
        )
        for attempt, job in rows.all()
    ]


@router.get("/providers/me/reputation", response_model=list[ReputationEventResponse])
async def my_reputation(
    provider: ProviderDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ReputationEvent]:
    """Return this provider's reputation events — why the score moved, newest first."""
    rows = await session.scalars(
        select(ReputationEvent)
        .where(ReputationEvent.provider_id == provider.id)
        .order_by(ReputationEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows)


@router.get("/providers/me/trust")
async def my_trust(provider: ProviderDep, session: SessionDep) -> dict:
    """Report the provider's trust source (Session 11.3): attested / benchmark / self_report."""
    has_valid = await session.scalar(
        select(BenchmarkReport)
        .where(
            BenchmarkReport.provider_id == provider.id,
            BenchmarkReport.validated.is_(True),
        )
        .limit(1)
    )
    return {
        "attested": provider.tee_attested,
        "benchmarked": has_valid is not None,
        "trust_source": trust_source(provider.tee_attested, has_valid is not None),
    }
