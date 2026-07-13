"""USDCPaymentProvider — the on-chain seam filling :class:`app.payments.PaymentProvider`.

The design constraint (proven balanced in the chaos drill): ``hold_escrow`` / ``settle`` /
``refund`` stay **exactly** off-chain — identical ledger postings to :class:`FiatStub`. Only
*aggregate* value touches the chain, and that is driven by the settlement engine, not here.

What this class adds over the stub is a **short-TTL cached read** of the developer's on-chain
escrow balance, used by the submit gate. The spendable balance is the conservative minimum of
two views that agree in steady state:

* the off-chain ledger's ``developer`` balance (deposits mirrored in by the watcher, minus
  holds), and
* the on-chain ``balanceOf`` minus outstanding off-chain escrow holds.

Taking the ``min`` means a lagging watcher, or a deposit orphaned by a reorg, can only ever make
the gate *stricter* — never let a developer commit money that isn't really there.
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.chain.client import ChainClient
from app.chain.units import from_units
from app.ledger import account_balance
from app.models import Developer, LedgerAccount
from app.payments import FiatStub


class USDCPaymentProvider(FiatStub):
    """Off-chain postings identical to the stub, plus cached on-chain balance reads."""

    def __init__(
        self,
        client: ChainClient,
        *,
        usdc_decimals: int = 6,
        cache_ttl_seconds: float = 5.0,
        clock=time.monotonic,
    ) -> None:
        self._client = client
        self._decimals = usdc_decimals
        self._ttl = cache_ttl_seconds
        self._clock = clock
        self._cache: dict[str, tuple[float, int]] = {}  # address -> (expires_at, raw units)

    async def onchain_escrow_units(self, address: str) -> int:
        """Cached ``GridixEscrow.balanceOf(address)`` in raw units (avoids an RPC per request)."""
        address = address.lower()
        now = self._clock()
        hit = self._cache.get(address)
        if hit is not None and hit[0] > now:
            return hit[1]
        units = await self._client.escrow_balance_of(address)
        self._cache[address] = (now + self._ttl, units)
        return units

    def invalidate(self, address: str) -> None:
        """Drop a cached balance (e.g. right after the watcher applies a deposit)."""
        self._cache.pop(address.lower(), None)

    async def available_balance(self, session: AsyncSession, developer: Developer) -> Decimal:
        """Spendable USDC for the submit gate: ``min(ledger_free, onchain − held)``.

        A developer with no linked wallet has no on-chain funds, so their spendable balance is
        purely their ledger ``developer`` balance (keeps fiat-only developers working).
        """
        ledger_free = await account_balance(session, LedgerAccount.developer, developer.id)
        if developer.wallet_address is None:
            return ledger_free
        held = await account_balance(session, LedgerAccount.escrow, developer.id)
        units = await self.onchain_escrow_units(developer.wallet_address)
        onchain = from_units(units, self._decimals)
        return min(ledger_free, onchain - held)

    async def can_afford(
        self, session: AsyncSession, developer: Developer, amount: Decimal
    ) -> bool:
        """Whether the developer can commit ``amount`` right now (the submit gate)."""
        return await self.available_balance(session, developer) >= amount


def as_usdc_provider(provider) -> USDCPaymentProvider | None:
    """Return ``provider`` if it is a USDCPaymentProvider, else ``None`` (fiat-only mode)."""
    return provider if isinstance(provider, USDCPaymentProvider) else None


# convenience re-export so callers can reference the id type without importing uuid here
DeveloperId = uuid.UUID
