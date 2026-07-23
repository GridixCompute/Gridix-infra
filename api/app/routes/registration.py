"""Registration endpoint: create a developer and mint a one-time API key.

Providers are NOT registered here. A provider is a capability of a wallet address
(see ``require_provider_principal``), so the only way to create one is
``POST /providers/onboard`` (providers.py) from an authenticated wallet session —
which binds the record to that address and mints the node's agent key. The old
``POST /providers`` factory minted providers with no wallet_address, records no
wallet session could ever reach; it is gone, and ``providers.wallet_address`` is
NOT NULL (migration 0025) so nothing can recreate them.
"""

from fastapi import APIRouter, status
from loguru import logger

from app.deps import SessionDep, SettingsDep
from app.models import ApiKey, Developer, OwnerType
from app.schemas import RegisterDeveloperRequest, RegisteredPrincipal
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
            key_hash=hash_api_key(plaintext, settings.api_hmac_key),
            prefix=key_prefix(plaintext),
        )
    )
    logger.info("registered developer {} ({})", developer.id, developer.name)
    return RegisteredPrincipal(id=developer.id, name=developer.name, api_key=plaintext)
