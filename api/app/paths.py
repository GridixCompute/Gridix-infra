"""Connection path negotiation — prefer direct P2P, fall back to relay (Session 7.4).

When the coordinator needs a data path to a provider it first tries a direct peer-to-peer
path (STUN/ICE-style hole punching). If the NAT topology makes that impossible (e.g. two
symmetric NATs) or the connectivity check fails, it transparently falls back to the relay
tunnel from 7.2/7.3. The chosen path is recorded per session and logged.

The NAT-feasibility matrix and the negotiation/fallback control flow live here and are
fully unit-tested. The actual STUN/ICE candidate gathering and UDP hole punching are the
injected ``connectivity_check`` — those need real networking and are validated on infra.
"""

import asyncio
import enum
from collections.abc import Awaitable, Callable
from datetime import datetime

from loguru import logger

from app.models import PathType, Provider


class NatType(enum.StrEnum):
    """Coarse NAT classification from a STUN probe (agent-reported)."""

    open = "open"  # public IP / full-cone — always directly reachable
    restricted = "restricted"  # (port-)restricted cone — usually punchable
    symmetric = "symmetric"  # per-destination mapping — generally not punchable


# A connectivity check attempts the actual hole punch and reports success. Injected so
# tests can simulate network outcomes without real UDP.
ConnectivityCheck = Callable[[], Awaitable[bool]]


def direct_feasible(local: NatType, remote: NatType) -> bool:
    """Whether a direct P2P path is plausible between two NAT types.

    An ``open`` peer is always reachable. Two symmetric NATs (or symmetric paired with a
    restricted cone) can't reliably hole-punch and must relay. Restricted↔restricted
    generally can.
    """
    if local is NatType.open or remote is NatType.open:
        return True
    # With no open peer, symmetric on either side isn't reliably punchable;
    # restricted ↔ restricted is.
    return NatType.symmetric not in (local, remote)


def provider_directly_reachable(provider_nat: NatType) -> bool:
    """Whether a publicly-reachable coordinator can hold a *direct* path to a provider.

    Open and restricted-cone providers are reachable via hole punching against the public
    coordinator. Symmetric-NAT providers are relayed: their per-destination port mapping
    makes a stable inbound path unreliable in practice, so we don't gamble on it.
    """
    return provider_nat is not NatType.symmetric


async def negotiate_path(
    local: NatType,
    remote: NatType,
    connectivity_check: ConnectivityCheck,
    *,
    timeout: float,
) -> PathType:
    """Decide the path: try direct when feasible, else (or on failure) relay.

    Returns :class:`PathType`. A direct result means the connectivity check succeeded
    within ``timeout``; anything else falls back to relay.
    """
    if not direct_feasible(local, remote):
        logger.info("path negotiation: NAT {}↔{} not punchable → relay", local, remote)
        return PathType.relay
    try:
        ok = await asyncio.wait_for(connectivity_check(), timeout)
    except (TimeoutError, Exception) as exc:  # noqa: BLE001 - any failure ⇒ fall back
        logger.info("path negotiation: direct check failed ({}) → relay", exc)
        return PathType.relay
    path = PathType.direct if ok else PathType.relay
    logger.info("path negotiation: {} (NAT {}↔{})", path, local, remote)
    return path


def record_path(provider: Provider, path_type: PathType, now: datetime) -> None:
    """Persist the negotiated path for the provider's current session."""
    provider.path_type = path_type
    provider.path_established_at = now


class ProviderChannel:
    """Send requests to a provider, preferring the direct path and falling back to relay.

    The fallback is transparent to callers: a direct send that raises is retried over the
    relay, and the channel's ``path_type`` is downgraded so subsequent sends skip the dead
    direct path.
    """

    def __init__(
        self,
        path_type: PathType,
        direct_send: Callable[[dict], Awaitable[dict]],
        relay_send: Callable[[dict], Awaitable[dict]],
    ) -> None:
        self.path_type = path_type
        self._direct_send = direct_send
        self._relay_send = relay_send

    async def send(self, request: dict) -> dict:
        """Send via the current path; on a direct-path failure, fall back to relay."""
        if self.path_type is PathType.direct:
            try:
                return await self._direct_send(request)
            except Exception as exc:  # noqa: BLE001 - degrade to relay, never hard-fail
                logger.warning("direct path failed, falling back to relay: {}", exc)
                self.path_type = PathType.relay
        return await self._relay_send(request)
