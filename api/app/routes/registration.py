"""Registration endpoints: create a developer or provider and mint a one-time API key."""

from fastapi import APIRouter, status
from loguru import logger

from app.deps import SessionDep, SettingsDep
from app.models import ApiKey, Developer, OwnerType, Provider
from app.schemas import (
    RegisterDeveloperRequest,
    RegisteredPrincipal,
    RegisterProviderRequest,
)
from app.security import generate_api_key, hash_api_key, key_prefix

router = APIRouter(tags=["registration"])


@router.post("/developers", response_model=RegisteredPrincipal, status_code=status.HTTP_201_CREATED)
async def register_developer(
    body: RegisterDeveloperRequest, session: SessionDep, settings: SettingsDep
) -> RegisteredPrincipal:
    """Create a developer and return its API key exactly once."""
    developer = Developer(name=body.name)
    session.add(developer)
    await session.flush()  # assign developer.id

    plaintext = generate_api_key()
    session.add(
        ApiKey(
            owner_type=OwnerType.developer,
            developer_id=developer.id,
            key_hash=hash_api_key(plaintext, settings.secret_key),
            prefix=key_prefix(plaintext),
        )
    )
    logger.info("registered developer {} ({})", developer.id, developer.name)
    return RegisteredPrincipal(id=developer.id, name=developer.name, api_key=plaintext)


@router.post("/providers", response_model=RegisteredPrincipal, status_code=status.HTTP_201_CREATED)
async def register_provider(
    body: RegisterProviderRequest, session: SessionDep, settings: SettingsDep
) -> RegisteredPrincipal:
    """Create a provider and return its API key exactly once."""
    provider = Provider(name=body.name, region=body.region)
    session.add(provider)
    await session.flush()  # assign provider.id

    plaintext = generate_api_key()
    session.add(
        ApiKey(
            owner_type=OwnerType.provider,
            provider_id=provider.id,
            key_hash=hash_api_key(plaintext, settings.secret_key),
            prefix=key_prefix(plaintext),
        )
    )
    logger.info("registered provider {} ({})", provider.id, provider.name)
    return RegisteredPrincipal(id=provider.id, name=provider.name, api_key=plaintext)
