"""Charging for inference — the settle path for instant dispatch.

Beside, not instead of, ``results._settle``: that one still resolves escrow for async
jobs, which still exist. This is what an inference request uses, and the shapes differ
enough that sharing would bend both.

The old flow escrows a worst-case amount at submit and reconciles at completion, because
a job runs for minutes on someone else's machine and the coordinator cannot know the cost
until it ends. An inference request answers in a second and reports what it actually
consumed, so there is nothing to hold: check the balance covers the worst case, dispatch,
then charge for what was really used. **A request that fails is never charged** — no hold
to strand, no refund to forget.

Money still moves only through balanced double-entry postings; balances stay derived.
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ledger import Posting, account_balance, post_transaction
from app.models import Developer, LedgerAccount, LedgerDirection

# USDC has six decimals on-chain. Every amount that reaches the ledger is quantised to
# them, so the number in the UI equals the number a contract would move.
USDC_PLACES = Decimal("0.000001")


class InsufficientBalanceError(RuntimeError):
    """The developer cannot cover the request. Raised BEFORE any work is dispatched."""

    def __init__(self, balance: Decimal, required: Decimal) -> None:
        super().__init__(f"balance {balance} < required {required}")
        self.balance = balance
        self.required = required


def quantize_usdc(amount: Decimal) -> Decimal:
    """Round to USDC's six decimals, half-up.

    Half-up, not banker's rounding: charges are compared against on-chain settlement, and
    a half-even cent here would drift from what the contract moved.
    """
    return Decimal(amount).quantize(USDC_PLACES, rounding=ROUND_HALF_UP)


async def developer_balance(session: AsyncSession, developer_id: uuid.UUID) -> Decimal:
    """Spendable balance: deposits credited in, charges debited out."""
    return await account_balance(session, LedgerAccount.developer, developer_id)


async def assert_can_afford(
    session: AsyncSession, developer_id: uuid.UUID, required: Decimal
) -> Decimal:
    """Check the developer covers ``required``, returning their balance.

    Called before dispatch: running the work first and discovering we cannot bill for it
    means the provider burned GPU time nobody pays for.

    Raises:
        InsufficientBalanceError: If the balance does not cover ``required``.
    """
    balance = await developer_balance(session, developer_id)
    if balance < required:
        raise InsufficientBalanceError(balance, quantize_usdc(required))
    return balance


async def charge_usage(
    session: AsyncSession,
    *,
    developer_id: uuid.UUID,
    provider_id: uuid.UUID,
    cost: Decimal,
    settings: Settings,
    job_id: uuid.UUID | None = None,
    reason: str = "inference_usage",
) -> Decimal:
    """Charge for one completed request: developer pays, provider earns net of the fee.

    Atomic against concurrent charges for the same developer. The balance is derived by
    summing ledger rows, so a read-then-write could let two requests each see enough and
    both post — overdrawing the account. Locking the developer row first serialises
    charges for that developer while leaving other developers untouched. (SQLite ignores
    FOR UPDATE, but its database-wide write lock gives the same ordering, so the hermetic
    tests exercise the same sequence.)

    Raises:
        InsufficientBalanceError: If the balance cannot cover ``cost`` — checked again
            here, under the lock, because the pre-dispatch check was optimistic.
    """
    cost = quantize_usdc(cost)
    if cost <= 0:
        return Decimal(0)

    await session.execute(
        select(Developer.id).where(Developer.id == developer_id).with_for_update()
    )

    balance = await developer_balance(session, developer_id)
    if balance < cost:
        raise InsufficientBalanceError(balance, cost)

    fee = quantize_usdc(cost * Decimal(settings.protocol_fee_bps) / Decimal(10_000))
    # The provider gets the remainder rather than a separately rounded number, so the
    # legs always net to zero — the ledger's one invariant.
    provider_earning = cost - fee

    postings = [
        Posting(LedgerAccount.developer, LedgerDirection.debit, cost, developer_id),
        Posting(LedgerAccount.provider, LedgerDirection.credit, provider_earning, provider_id),
    ]
    if fee > 0:
        postings.append(Posting(LedgerAccount.protocol, LedgerDirection.credit, fee))

    await post_transaction(session, postings, reason=reason, job_id=job_id)
    return cost


async def credit_deposit(
    session: AsyncSession,
    *,
    developer_id: uuid.UUID,
    amount: Decimal,
    reason: str = "deposit",
) -> Decimal:
    """Credit a developer's balance from an on-chain deposit.

    Funded from the protocol boundary, the same way ``ledger.deposit_stake`` funds stake:
    value entering the system has to come from somewhere for the legs to net to zero.
    """
    amount = quantize_usdc(amount)
    if amount <= 0:
        return Decimal(0)
    await post_transaction(
        session,
        [
            Posting(LedgerAccount.protocol, LedgerDirection.debit, amount),
            Posting(LedgerAccount.developer, LedgerDirection.credit, amount, developer_id),
        ],
        reason=reason,
    )
    return amount
