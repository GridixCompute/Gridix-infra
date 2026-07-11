"""Bandwidth accounting (Session 7.7).

Records bytes moved to/from each provider at the data-movement points (input/model
downloads, result uploads) and aggregates them per provider and per session. Exposed for
observability now and for bandwidth-based pricing later (a data-cost line item on
settlement). Accounting is best-effort and approximate — it meters payload sizes, not
wire bytes.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BandwidthDirection, BandwidthEvent


async def record_bandwidth(
    session: AsyncSession,
    provider_id: uuid.UUID,
    direction: BandwidthDirection,
    num_bytes: int,
    *,
    job_id: uuid.UUID | None = None,
) -> None:
    """Append a bandwidth event (no-op for non-positive sizes)."""
    if num_bytes <= 0:
        return
    session.add(
        BandwidthEvent(
            provider_id=provider_id,
            job_id=job_id,
            direction=direction,
            num_bytes=num_bytes,
        )
    )


async def provider_bandwidth(
    session: AsyncSession, provider_id: uuid.UUID, *, since: datetime | None = None
) -> dict[str, int]:
    """Return ``{ingress, egress, total}`` byte totals for a provider.

    ``since`` scopes the window (e.g. the current session's ``connected_at``).
    """
    query = (
        select(BandwidthEvent.direction, func.coalesce(func.sum(BandwidthEvent.num_bytes), 0))
        .where(BandwidthEvent.provider_id == provider_id)
        .group_by(BandwidthEvent.direction)
    )
    if since is not None:
        query = query.where(BandwidthEvent.created_at >= since)

    totals = {BandwidthDirection.ingress: 0, BandwidthDirection.egress: 0}
    for direction, total in await session.execute(query):
        totals[BandwidthDirection(direction)] = int(total)
    ingress = totals[BandwidthDirection.ingress]
    egress = totals[BandwidthDirection.egress]
    return {"ingress": ingress, "egress": egress, "total": ingress + egress}


async def job_bytes(session: AsyncSession, job_id: uuid.UUID) -> int:
    """Total bytes moved on behalf of a job (both directions) — for data-cost billing."""
    total = await session.scalar(
        select(func.coalesce(func.sum(BandwidthEvent.num_bytes), 0)).where(
            BandwidthEvent.job_id == job_id
        )
    )
    return int(total or 0)
