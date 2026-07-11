"""Double-entry ledger — the money abstraction.

Every value movement is a balanced *transaction*: a set of rows sharing an
``entry_group`` where total debits equal total credits. Rows are append-only; a
correction is a new balancing group, never an update. Balances are derived
(``credits - debits`` per account), so the ledger is the single source of truth.

This is fiat-first and provider-agnostic: on-chain settlement later swaps the
``PaymentProvider`` (Session 6) that drives these postings, not this table. The
``protocol`` account doubles as the external boundary — money entering (a stake
deposit, an escrow) or leaving the system balances against it.

Session 5 uses the stake/slash primitives; Session 6 adds escrow/settle/refund on the
same foundation.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LedgerAccount, LedgerDirection, LedgerEntry


class UnbalancedTransactionError(ValueError):
    """Raised when a transaction's debits and credits do not net to zero."""


@dataclass(frozen=True)
class Posting:
    """One leg of a transaction."""

    account: LedgerAccount
    direction: LedgerDirection
    amount: Decimal
    account_ref: uuid.UUID | None = None


async def post_transaction(
    session: AsyncSession,
    postings: list[Posting],
    *,
    reason: str,
    job_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Append a balanced set of ledger rows and return their ``entry_group`` id.

    Raises:
        UnbalancedTransactionError: If debits and credits do not net to zero, or the
            posting set is empty.
    """
    if not postings:
        raise UnbalancedTransactionError("transaction has no postings")
    debits = sum((p.amount for p in postings if p.direction is LedgerDirection.debit), Decimal(0))
    credits = sum((p.amount for p in postings if p.direction is LedgerDirection.credit), Decimal(0))
    if debits != credits:
        raise UnbalancedTransactionError(f"debits {debits} != credits {credits}")

    group = uuid.uuid4()
    for p in postings:
        session.add(
            LedgerEntry(
                entry_group=group,
                job_id=job_id,
                account=p.account,
                account_ref=p.account_ref,
                direction=p.direction,
                amount=p.amount,
                reason=reason,
            )
        )
    await session.flush()
    return group


async def account_balance(
    session: AsyncSession, account: LedgerAccount, account_ref: uuid.UUID | None = None
) -> Decimal:
    """Return ``credits - debits`` for an account (optionally scoped to a ref)."""

    def _sum(direction: LedgerDirection):
        q = select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.account == account, LedgerEntry.direction == direction
        )
        if account_ref is not None:
            q = q.where(LedgerEntry.account_ref == account_ref)
        return q

    credit = await session.scalar(_sum(LedgerDirection.credit))
    debit = await session.scalar(_sum(LedgerDirection.debit))
    return Decimal(str(credit or 0)) - Decimal(str(debit or 0))


async def provider_stake(session: AsyncSession, provider_id: uuid.UUID) -> Decimal:
    """Return a provider's current stake balance."""
    return await account_balance(session, LedgerAccount.stake, provider_id)


async def verify_ledger_integrity(session: AsyncSession) -> list[tuple[uuid.UUID, Decimal]]:
    """Return every unbalanced transaction group (Session 12.4 DR check).

    Each ``entry_group`` must have equal debits and credits. An empty result means the
    ledger has zero discrepancy — the invariant to confirm after a backup restore.
    """
    debit = func.sum(
        case((LedgerEntry.direction == LedgerDirection.debit, LedgerEntry.amount), else_=0)
    )
    credit = func.sum(
        case((LedgerEntry.direction == LedgerDirection.credit, LedgerEntry.amount), else_=0)
    )
    rows = await session.execute(
        select(LedgerEntry.entry_group, debit, credit).group_by(LedgerEntry.entry_group)
    )
    discrepancies: list[tuple[uuid.UUID, Decimal]] = []
    for group, d, c in rows:
        delta = Decimal(str(d or 0)) - Decimal(str(c or 0))
        if delta != 0:
            discrepancies.append((group, delta))
    return discrepancies


async def deposit_stake(
    session: AsyncSession, provider_id: uuid.UUID, amount: Decimal
) -> uuid.UUID:
    """Credit a provider's stake, funded from the external (protocol) boundary."""
    return await post_transaction(
        session,
        [
            Posting(LedgerAccount.protocol, LedgerDirection.debit, amount),
            Posting(LedgerAccount.stake, LedgerDirection.credit, amount, provider_id),
        ],
        reason="stake_deposit",
    )


async def slash_stake(
    session: AsyncSession,
    provider_id: uuid.UUID,
    amount: Decimal,
    *,
    job_id: uuid.UUID | None = None,
) -> Decimal:
    """Debit up to ``amount`` from a provider's stake to the protocol. Returns the amount
    actually slashed (capped at the current balance so stake never goes negative)."""
    current = await provider_stake(session, provider_id)
    slashed = min(amount, current)
    if slashed <= 0:
        return Decimal(0)
    await post_transaction(
        session,
        [
            Posting(LedgerAccount.stake, LedgerDirection.debit, slashed, provider_id),
            Posting(LedgerAccount.protocol, LedgerDirection.credit, slashed),
        ],
        reason="slash",
        job_id=job_id,
    )
    return slashed
