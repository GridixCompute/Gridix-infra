"""Provider self-service endpoints: declare capabilities, read back state, bandwidth."""

from fastapi import APIRouter
from sqlalchemy import select

from app.bandwidth import provider_bandwidth
from app.benchmark import trust_source
from app.deps import ProviderDep, SessionDep
from app.models import BenchmarkReport
from app.schemas import (
    BandwidthResponse,
    BenchmarkResponse,
    ProviderCapabilities,
    ProviderResponse,
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
