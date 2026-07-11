"""Peer-assisted artifact distribution (Session 8.7) — interface, behind a flag.

Popular artifacts (base images, common models) can be seeded provider-to-provider instead
of always pulled from origin, saving coordinator egress. This module is the *interface*
and placement policy; the actual peer transfer runs over the tunnel/direct path. It is
off by default (``peer_distribution_enabled``) and, when disabled, every fetch resolves to
origin — so enabling it is purely additive.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import ProviderArtifact


@dataclass(frozen=True)
class FetchSource:
    """Where a provider should fetch an artifact from."""

    kind: Literal["origin", "peer"]
    provider_id: uuid.UUID | None = None


async def seeders_for(
    session: AsyncSession, digest: str, *, exclude: uuid.UUID | None = None
) -> list[uuid.UUID]:
    """Return provider ids that currently cache ``digest`` (candidate seeders)."""
    query = select(ProviderArtifact.provider_id).where(ProviderArtifact.digest == digest)
    if exclude is not None:
        query = query.where(ProviderArtifact.provider_id != exclude)
    return list(await session.scalars(query))


async def plan_fetch(
    session: AsyncSession,
    requester_id: uuid.UUID,
    digest: str,
    settings: Settings,
) -> FetchSource:
    """Decide where ``requester_id`` should fetch ``digest`` from.

    When peer distribution is enabled and another provider already holds the artifact, the
    fetch is planned from that peer; otherwise (disabled, or no seeder) it falls back to
    origin. Origin is always a valid answer, so the feature never blocks a fetch.
    """
    if not settings.peer_distribution_enabled:
        return FetchSource(kind="origin")
    seeders = await seeders_for(session, digest, exclude=requester_id)
    if seeders:
        return FetchSource(kind="peer", provider_id=seeders[0])
    return FetchSource(kind="origin")
