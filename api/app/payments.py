"""Payment provider abstraction — the seam between accounting and money movement.

The double-entry :mod:`app.ledger` is the accounting truth. A ``PaymentProvider`` drives
the postings for the business events (escrow, settle, refund). Today the only
implementation is :class:`FiatStub`, which records the movements in the ledger without a
real gateway; an on-chain implementation later swaps this class, not the ledger schema or
the call sites. No token/buyback/burn logic lives here — that stays out of this repo.

Escrow correctness is the whole point: value only ever moves developer → escrow at
submit, and escrow → provider (+ protocol fee) on *verified* completion or escrow →
developer on failure. There is no path that pays a provider for unverified work or
charges a developer for a failed job.
"""

import uuid
from abc import ABC, abstractmethod
from decimal import Decimal

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.ledger import Posting, post_transaction
from app.models import LedgerAccount, LedgerDirection


class PaymentProvider(ABC):
    """Moves value between developer, escrow, provider, and protocol accounts."""

    @abstractmethod
    async def hold_escrow(
        self, session: AsyncSession, job_id: uuid.UUID, developer_id: uuid.UUID, amount: Decimal
    ) -> None:
        """Move ``amount`` from the developer into escrow at submit."""

    @abstractmethod
    async def settle(
        self,
        session: AsyncSession,
        job_id: uuid.UUID,
        developer_id: uuid.UUID,
        provider_id: uuid.UUID,
        cost: Decimal,
        fee: Decimal,
    ) -> None:
        """Release ``cost`` from escrow: ``cost - fee`` to the provider, ``fee`` to protocol."""

    @abstractmethod
    async def refund(
        self, session: AsyncSession, job_id: uuid.UUID, developer_id: uuid.UUID, amount: Decimal
    ) -> None:
        """Return ``amount`` from escrow to the developer."""


class FiatStub(PaymentProvider):
    """Fiat-first stub: records movements in the ledger, no external gateway calls."""

    async def hold_escrow(
        self, session: AsyncSession, job_id: uuid.UUID, developer_id: uuid.UUID, amount: Decimal
    ) -> None:
        if amount <= 0:
            return
        await post_transaction(
            session,
            [
                Posting(LedgerAccount.developer, LedgerDirection.debit, amount, developer_id),
                Posting(LedgerAccount.escrow, LedgerDirection.credit, amount, developer_id),
            ],
            reason="escrow_hold",
            job_id=job_id,
        )
        logger.info("escrowed {} for job {} (developer {})", amount, job_id, developer_id)

    async def settle(
        self,
        session: AsyncSession,
        job_id: uuid.UUID,
        developer_id: uuid.UUID,
        provider_id: uuid.UUID,
        cost: Decimal,
        fee: Decimal,
    ) -> None:
        if cost <= 0:
            return
        # Debit escrow scoped to the developer so their escrow nets to zero at settlement.
        postings = [Posting(LedgerAccount.escrow, LedgerDirection.debit, cost, developer_id)]
        net = cost - fee
        if net > 0:
            postings.append(
                Posting(LedgerAccount.provider, LedgerDirection.credit, net, provider_id)
            )
        if fee > 0:
            postings.append(Posting(LedgerAccount.protocol, LedgerDirection.credit, fee))
        await post_transaction(session, postings, reason="settle", job_id=job_id)
        logger.info("settled job {}: {} to provider {} ({} fee)", job_id, net, provider_id, fee)

    async def refund(
        self, session: AsyncSession, job_id: uuid.UUID, developer_id: uuid.UUID, amount: Decimal
    ) -> None:
        if amount <= 0:
            return
        await post_transaction(
            session,
            [
                Posting(LedgerAccount.escrow, LedgerDirection.debit, amount, developer_id),
                Posting(LedgerAccount.developer, LedgerDirection.credit, amount, developer_id),
            ],
            reason="refund",
            job_id=job_id,
        )
        logger.info("refunded {} to developer {} for job {}", amount, developer_id, job_id)


_provider: PaymentProvider = FiatStub()


def get_payment_provider() -> PaymentProvider:
    """Return the active payment provider (FiatStub for the MVP)."""
    return _provider


def set_payment_provider(provider: PaymentProvider) -> None:
    """Install a payment provider (the on-chain seam)."""
    global _provider
    _provider = provider
