"""Provider self-service endpoints: declare and read back capabilities."""

from fastapi import APIRouter

from app.deps import ProviderDep, SessionDep
from app.schemas import ProviderCapabilities, ProviderResponse

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
