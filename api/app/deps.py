"""FastAPI dependencies: authentication and current-principal resolution.

Callers present their API key as ``Authorization: Bearer <key>``. The key is hashed and
looked up; the row's ``owner_type`` gates access to developer- vs provider-only routes.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import ApiKey, Developer, OwnerType, Provider
from app.security import hash_api_key

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
    """Resolve and validate the presented key, returning the live ApiKey row."""
    token = _extract_bearer(authorization)
    digest = hash_api_key(token, settings.secret_key)
    key = await session.scalar(select(ApiKey).where(ApiKey.key_hash == digest))
    if key is None or key.revoked:
        raise _UNAUTHORIZED
    return key


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


DeveloperDep = Annotated[Developer, Depends(require_developer)]
ProviderDep = Annotated[Provider, Depends(require_provider)]


async def require_internal(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Gate operator-only endpoints (dispute rulings) with the shared internal secret."""
    if authorization != f"Bearer {settings.secret_key}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Operator credentials required."
        )


InternalDep = Annotated[None, Depends(require_internal)]
