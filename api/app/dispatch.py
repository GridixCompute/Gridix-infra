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
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import aclosing, contextmanager
from dataclasses import dataclass
from datetime import datetime

import httpx
from fastapi import status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ledger import provider_stake
from app.models import DataTier, Provider, ProviderModel
from app.presence import is_connected
from app.relay_client import RelayUnavailableError, call_provider, stream_provider


class NoNodeAvailableError(RuntimeError):
    """No connected node can serve the request under the placement rules."""


class DispatchError(RuntimeError):
    """The node was reachable but the request did not produce a usable result."""


class DispatchTimeoutError(DispatchError):
    """The node took the work and never answered.

    Distinct from a node error: the work may still be burning GPU somewhere, and the
    caller deserves 504 rather than 502. A subclass, so callers that only care that
    dispatch failed still catch DispatchError.
    """


@dataclass(frozen=True)
class Candidate:
    """A provider that may receive this request, with the load used to rank it."""

    provider_id: uuid.UUID
    inflight: int


# Requests currently out on each node, counted in this process.
#
# Deliberately local, and honest about it: a request is in flight only while a coroutine
# here awaits its reply, so the process holding that coroutine is the only one that knows.
# Across replicas each sees its own share, which biases selection but never breaks it —
# every replica still spreads its own load, and a node's real ceiling is enforced by the
# node. Making this global would mean a round trip to Redis on the hot path to sharpen a
# heuristic, and a stuck counter would strand a healthy node.
_inflight: Counter[uuid.UUID] = Counter()


@contextmanager
def track_inflight(provider_id: uuid.UUID):
    """Count a request against a node for as long as it is out.

    The decrement is in a finally: a node that errors or times out must not look busy
    forever, or one bad request retires it from selection.
    """
    _inflight[provider_id] += 1
    try:
        yield
    finally:
        _inflight[provider_id] -= 1
        if _inflight[provider_id] <= 0:
            del _inflight[provider_id]


def inflight_count(provider_id: uuid.UUID) -> int:
    """How many requests this process currently has out on ``provider_id``."""
    return _inflight[provider_id]


def reset_inflight() -> None:
    """Drop all counts. For tests; nothing in production should need this."""
    _inflight.clear()


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
        candidates.append(Candidate(provider_id=provider.id, inflight=inflight_count(provider.id)))
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
    with track_inflight(provider_id):
        try:
            reply = await call_provider(
                provider_id, method=method, payload=payload, settings=settings, job_id=job_id
            )
        except RelayUnavailableError as exc:
            # The node dropped between selection and dispatch, or the relay is down.
            # Callers may retry against another node; that choice isn't ours to make here.
            raise DispatchError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            # call_provider raise_for_status()es outside its own try, so the relay's own
            # status codes surface here rather than as RelayUnavailableError. 504 is the
            # relay telling us the node went quiet mid-request.
            if exc.response.status_code == status.HTTP_504_GATEWAY_TIMEOUT:
                raise DispatchTimeoutError(f"node {provider_id} did not respond") from exc
            raise DispatchError(f"relay returned {exc.response.status_code}") from exc
        except TimeoutError as exc:
            raise DispatchTimeoutError(f"node {provider_id} did not respond") from exc

    node_status = reply.get("status", 200)
    if node_status >= 400:
        logger.warning("node {} returned status {} for {}", provider_id, node_status, method)
        raise DispatchError(f"node returned status {node_status}")
    return reply.get("payload") or {}


async def dispatch_stream(
    provider_id: uuid.UUID,
    *,
    method: str,
    payload: dict,
    settings: Settings,
    job_id: str | None = None,
) -> AsyncIterator[dict]:
    """Stream a request to a node, yielding ``chunk`` frames then one terminal frame.

    The terminal frame is either ``{"type": "response", ...}`` (the node finished) or
    ``{"type": "error", ...}`` (the node or the tunnel failed). Both are yielded rather than
    raised, because by the time they arrive the caller has already sent bytes to its own
    client and has partial work to account for — an exception would discard the very context
    the billing decision needs. Failures BEFORE the first frame still raise, since nothing
    has been produced and the unary error mapping applies unchanged.

    Ending iteration early closes the underlying HTTP stream, which is how a client
    disconnect reaches the node as a cancel. Callers should therefore drain or close this
    promptly rather than abandoning it to the garbage collector.
    """
    with track_inflight(provider_id):
        try:
            async with aclosing(
                stream_provider(
                    provider_id, method=method, payload=payload, settings=settings, job_id=job_id
                )
            ) as frames:
                async for frame in frames:
                    yield frame
        except RelayUnavailableError as exc:
            raise DispatchError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == status.HTTP_504_GATEWAY_TIMEOUT:
                raise DispatchTimeoutError(f"node {provider_id} did not respond") from exc
            raise DispatchError(f"relay returned {exc.response.status_code}") from exc
        except TimeoutError as exc:
            raise DispatchTimeoutError(f"node {provider_id} did not respond") from exc
