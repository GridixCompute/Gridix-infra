"""FastAPI dependencies: authentication and current-principal resolution.

Callers present their API key as ``Authorization: Bearer <key>``. The key is hashed and
looked up; the row's ``owner_type`` gates access to developer- vs provider-only routes.
"""

import hmac
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import ApiKey, Developer, OwnerType, Provider
from app.security import hash_api_key
from app.siwe import as_utc

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Missing or invalid API key.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_bearer(authorization: str | None) -> str:
    """Pull the raw key out of an ``Authorization: Bearer <key>`` header."""
    if not authorization:
        raise _UNAUTHORIZED
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _UNAUTHORIZED
    return token.strip()


async def _resolve_key(
    authorization: str | None, session: AsyncSession, settings: Settings
) -> ApiKey:
    """Resolve and validate the presented key, returning the live ApiKey row.

    Both credential kinds arrive here: a browser session minted by wallet sign-in (which
    expires) and a programmatic key generated in /settings (which does not, until it is
    revoked). One path, so an expiry or revocation check can never be enforced on one and
    forgotten on the other.
    """
    token = _extract_bearer(authorization)
    try:
        digest = hash_api_key(token, settings.api_hmac_key)
    except ValueError:
        # Too long to be a key we issued — reject without hashing it (L1).
        raise _UNAUTHORIZED from None
    key = await session.scalar(select(ApiKey).where(ApiKey.key_hash == digest))
    if key is None or key.revoked or _is_expired(key):
        raise _UNAUTHORIZED
    return key


def _is_expired(key: ApiKey) -> bool:
    """Whether a key's lifetime has run out. NULL expires_at means it never does."""
    if key.expires_at is None:
        return False
    return as_utc(key.expires_at) <= datetime.now(UTC)


async def require_developer(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Developer:
    """Authenticate a developer, returning the Developer row. 403 for provider keys."""
    key = await _resolve_key(authorization, session, settings)
    if key.owner_type is not OwnerType.developer or key.developer_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Developer credentials required."
        )
    developer = await session.get(Developer, key.developer_id)
    if developer is None:
        raise _UNAUTHORIZED
    return developer


async def require_provider(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Provider:
    """Authenticate a provider, returning the Provider row. 403 for developer keys."""
    key = await _resolve_key(authorization, session, settings)
    if key.owner_type is not OwnerType.provider or key.provider_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Provider credentials required."
        )
    provider = await session.get(Provider, key.provider_id)
    if provider is None:
        raise _UNAUTHORIZED
    return provider


async def provider_signing_key(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """The raw provider key from the ``Authorization`` header, for verifying HMAC-signed
    submissions (e.g. benchmark reports).

    The provider is authenticated separately by ``ProviderDep``; the stored API key is
    only ever a hash, so the sole place the coordinator can verify a provider-key HMAC
    is against the bearer token presented on this very request. This returns that token.
    """
    return _extract_bearer(authorization)


DeveloperDep = Annotated[Developer, Depends(require_developer)]
ProviderDep = Annotated[Provider, Depends(require_provider)]
ProviderKeyDep = Annotated[str, Depends(provider_signing_key)]


async def require_internal(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Gate operator-only endpoints (dispute rulings) with the operator secret.

    Uses ``operator_key`` — NOT the API-key HMAC secret — so a developer or provider
    who holds a valid API key can never present it (or anything derived from the
    HMAC secret) as operator credentials. Compared in constant time to avoid a
    timing side-channel.
    """
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip(), settings.operator_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Operator credentials required."
        )


InternalDep = Annotated[None, Depends(require_internal)]
