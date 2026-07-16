"""Inference dispatch — pick a node that can serve a model, and send it the work.

This is the instant-dispatch replacement for the queue/scheduler path: a caller asks for
a model, we choose a connected node that serves it, and push the request down that node's
relay tunnel, blocking for the reply.

Node selection is a query, not a lookup in this process's memory. The tunnels live in the
relay; any API replica may need to dispatch. A registry held in one process would be
correct only in that process.

Selection carries the placement rules that ``matcher.py`` enforces for the old engine.
They are policy about *who may be given work*, not about how work is scheduled, so they
outlive the scheduler:

* confidential work runs only on attested TEE hardware (``matcher.py:87``),
* under-staked providers get nothing (``matcher.py:135-141``) — the gate that makes stake
  mean something,
* disabled/degraded providers are skipped (``matcher.py:76``).

They are re-implemented here rather than imported so that deleting the old engine cannot
quietly take them along. `tests/test_dispatch.py` proves each one from this side.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ledger import provider_stake
from app.models import DataTier, Provider, ProviderModel
from app.presence import is_connected
from app.relay_client import RelayUnavailableError, call_provider


class NoNodeAvailableError(RuntimeError):
    """No connected node can serve the request under the placement rules."""


class DispatchError(RuntimeError):
    """The node was reachable but the request did not produce a usable result."""


@dataclass(frozen=True)
class Candidate:
    """A provider that may receive this request, with the load used to rank it."""

    provider_id: uuid.UUID
    inflight: int


async def eligible_nodes(
    session: AsyncSession,
    *,
    model: str,
    now: datetime,
    settings: Settings,
    data_tier: DataTier = DataTier.public,
) -> list[Candidate]:
    """Connected providers that may serve ``model``, least-loaded first.

    Everything the placement rules reject is filtered here rather than after selection, so
    an ineligible provider is never dispatched to and then rolled back.
    """
    rows = (
        await session.scalars(
            select(Provider)
            .join(ProviderModel, ProviderModel.provider_id == Provider.id)
            .where(ProviderModel.model == model, Provider.enabled.is_(True))
        )
    ).all()

    candidates: list[Candidate] = []
    for provider in rows:
        if provider.degraded:
            continue
        if not is_connected(provider, now, settings.connection_timeout_seconds):
            continue
        # Confidential work never lands on unattested hardware. This is the ONLY
        # placement gate for it once matcher.py is gone; key_broker refusing the key
        # afterwards is a second line, not a substitute.
        if data_tier is DataTier.confidential_tee and not provider.tee_attested:
            continue
        # Stake is the collateral canary slashing bites into. A provider below the
        # minimum has nothing at risk, so it gets no work.
        if await provider_stake(session, provider.id) < settings.min_provider_stake:
            continue
        candidates.append(Candidate(provider_id=provider.id, inflight=0))
    return candidates


async def select_node(
    session: AsyncSession,
    *,
    model: str,
    now: datetime,
    settings: Settings,
    data_tier: DataTier = DataTier.public,
) -> uuid.UUID:
    """Choose the least-loaded eligible node for ``model``.

    Raises:
        NoNodeAvailableError: If nothing connected may serve it.
    """
    candidates = await eligible_nodes(
        session, model=model, now=now, settings=settings, data_tier=data_tier
    )
    if not candidates:
        raise NoNodeAvailableError(f"no connected node serves {model!r}")
    return min(candidates, key=lambda c: c.inflight).provider_id


async def dispatch(
    provider_id: uuid.UUID,
    *,
    method: str,
    payload: dict,
    settings: Settings,
    job_id: str | None = None,
) -> dict:
    """Send a request down a node's tunnel and return its reply.

    Raises:
        DispatchError: If the node is unreachable, times out, or answers with a failure.
    """
    try:
        reply = await call_provider(
            provider_id, method=method, payload=payload, settings=settings, job_id=job_id
        )
    except RelayUnavailableError as exc:
        # The node dropped between selection and dispatch, or the relay is down. Callers
        # may retry against another node; that choice isn't ours to make here.
        raise DispatchError(str(exc)) from exc

    status = reply.get("status", 200)
    if status >= 400:
        logger.warning("node {} returned status {} for {}", provider_id, status, method)
        raise DispatchError(f"node returned status {status}")
    return reply.get("payload") or {}
