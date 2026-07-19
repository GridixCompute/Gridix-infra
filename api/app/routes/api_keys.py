"""Programmatic API keys: mint, list, revoke.

The credential a wallet sign-in mints is a browser session — it expires, and it lives in
an httpOnly cookie the user never sees. Calling GRIDIX from a script needs something
else: a long-lived key the developer holds deliberately. This is where they get one.

Every route here is gated on ``WalletSessionDep``, not ``DeveloperDep``. See
``require_wallet_session`` for why a key must not be able to mint a key.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from sqlalchemy import select

from app.deps import SessionDep, SettingsDep, WalletSessionDep
from app.models import ApiKey, ApiKeyKind, Developer, OwnerType
from app.schemas import ApiKeyResponse, CreateApiKeyRequest, CreatedApiKey
from app.security import generate_api_key, hash_api_key, key_prefix

router = APIRouter(prefix="/developers/me/keys", tags=["api-keys"])


def _owned_programmatic(developer: Developer):
    """Keys this developer may manage: their own, and only the programmatic ones.

    Sessions are deliberately out of scope. They are managed by signing in and out, and
    exposing them here would invite a developer to revoke the very session making the
    request — a self-inflicted lockout with no matching "sign out" affordance.
    """
    return select(ApiKey).where(
        ApiKey.developer_id == developer.id,
        ApiKey.owner_type == OwnerType.developer,
        ApiKey.kind == ApiKeyKind.programmatic,
    )


@router.post("", response_model=CreatedApiKey, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: CreateApiKeyRequest,
    developer: WalletSessionDep,
    session: SessionDep,
    settings: SettingsDep,
) -> CreatedApiKey:
    """Mint a long-lived key and return its plaintext — the only time it is ever shown."""
    plaintext = generate_api_key()
    key = ApiKey(
        owner_type=OwnerType.developer,
        developer_id=developer.id,
        key_hash=hash_api_key(plaintext, settings.api_hmac_key),
        prefix=key_prefix(plaintext),
        kind=ApiKeyKind.programmatic,
        label=body.label,
        # No expiry: this is the credential a cron job or CI runner authenticates with,
        # and a key that dies on its own turns into a 3am outage. Revocation is the
        # control here, and it is immediate.
        expires_at=None,
    )
    session.add(key)
    await session.flush()  # assign key.id

    logger.info("developer {} minted programmatic key {}", developer.id, key.id)
    return CreatedApiKey(id=key.id, label=key.label, prefix=key.prefix, api_key=plaintext)


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(developer: WalletSessionDep, session: SessionDep) -> list[ApiKey]:
    """List this developer's programmatic keys. No plaintext — it is not recoverable."""
    rows = await session.scalars(_owned_programmatic(developer).order_by(ApiKey.created_at.desc()))
    return list(rows)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID, developer: WalletSessionDep, session: SessionDep
) -> None:
    """Revoke a key. It stops authenticating on the next request that presents it."""
    key = await session.scalar(_owned_programmatic(developer).where(ApiKey.id == key_id))
    if key is None:
        # 404 for "someone else's key" as well as "no such key": distinguishing them
        # would confirm the existence of another developer's credential by id.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such API key.")

    key.revoked = True
    logger.info("developer {} revoked programmatic key {}", developer.id, key.id)
