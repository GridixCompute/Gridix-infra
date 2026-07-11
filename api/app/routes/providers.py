"""Provider self-service endpoints: declare capabilities, read back state, bandwidth."""

from fastapi import APIRouter

from app.bandwidth import provider_bandwidth
from app.deps import ProviderDep, SessionDep
from app.schemas import BandwidthResponse, ProviderCapabilities, ProviderResponse

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
