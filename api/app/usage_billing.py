"""Charging for inference — the settle path for instant dispatch.

Beside, not instead of, ``results._settle``: that one still resolves escrow for async
jobs, which still exist. This is what an inference request uses, and the shapes differ
enough that sharing would bend both.

The old flow escrows a worst-case amount at submit and reconciles at completion, because
a job runs for minutes on someone else's machine and the coordinator cannot know the cost
until it ends. An inference request answers in a second and reports what it actually
consumed. It once looked like there was nothing to hold — check the balance, dispatch,
charge for what was used — but that check was a bare read with no reservation, so two
concurrent requests from one developer with balance for one both passed it and both
dispatched, burning a provider's GPU on the request that could not be paid for. The gate
promised "never burn a provider's GPU" and broke it under concurrency.

So the inference path now holds too, joining the escrow model the job path always used:
``reserve_balance`` locks the developer row, checks the *available* balance (deposits minus
active holds), and moves the worst case developer -> escrow before a node is touched. A
second concurrent request sees the first's hold as reduced balance and is refused AT THE
GATE, not after the work is done. ``settle_reservation`` returns the hold and charges the
actual cost on success; ``release_reservation`` returns it untouched on failure. **A
request that fails is still never charged**, and now a request that cannot be paid for
never reaches a node either.

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


async def reserve_balance(
    session: AsyncSession, *, developer_id: uuid.UUID, amount: Decimal
) -> Decimal:
    """Reserve ``amount`` against the developer's balance before a node is dispatched.

    This is the pre-dispatch gate, and it must be atomic against concurrent requests or it
    is no gate at all. ``assert_can_afford`` used to be a bare balance read: two requests
    from one developer with balance for one both read the full balance, both passed, both
    dispatched, and one was refused only at charge time — after a provider's GPU had already
    run for the request that could not be paid for.

    Reserving fixes that. The developer row is locked (``SELECT ... FOR UPDATE``) so
    concurrent reservations for the same developer serialise; the available balance is the
    derived developer balance, which already nets out every active hold (a hold debits the
    developer account); and if it covers ``amount`` the worst case is moved developer ->
    escrow and committed. The commit releases the lock immediately, so requests are
    serialised only across the reservation, not across dispatch. A second request then reads
    the reduced balance and is refused HERE, before any node is touched.

    (SQLite ignores ``FOR UPDATE``; its database-wide write lock does not serialise the two
    balance *reads*, so the concurrency guarantee is proven on Postgres — see
    tests/integration/test_postgres_overdraw.py.)

    Returns the quantised amount actually held (the handle callers pass back to settle or
    release). Raises ``InsufficientBalanceError`` if the available balance cannot cover it.
    """
    amount = quantize_usdc(amount)
    if amount <= 0:
        return Decimal(0)

    await session.execute(
        select(Developer.id).where(Developer.id == developer_id).with_for_update()
    )

    balance = await developer_balance(session, developer_id)
    if balance < amount:
        raise InsufficientBalanceError(balance, amount)

    await post_transaction(
        session,
        [
            Posting(LedgerAccount.developer, LedgerDirection.debit, amount, developer_id),
            Posting(LedgerAccount.escrow, LedgerDirection.credit, amount, developer_id),
        ],
        reason="inference_hold",
    )
    # Commit here, not at the end of the request: the hold has to be visible to concurrent
    # requests (and the lock released) before this one spends seconds in dispatch. Holding
    # the lock across dispatch would serialise every request for this developer instead.
    await session.commit()
    return amount


async def _return_hold(session: AsyncSession, *, developer_id: uuid.UUID, held: Decimal) -> None:
    """Move a held reservation back out of escrow to the developer (escrow nets to zero)."""
    held = quantize_usdc(held)
    if held <= 0:
        return
    await post_transaction(
        session,
        [
            Posting(LedgerAccount.escrow, LedgerDirection.debit, held, developer_id),
            Posting(LedgerAccount.developer, LedgerDirection.credit, held, developer_id),
        ],
        reason="inference_hold_release",
    )


async def settle_reservation(
    session: AsyncSession,
    *,
    developer_id: uuid.UUID,
    provider_id: uuid.UUID,
    held: Decimal,
    actual: Decimal,
    settings: Settings,
) -> Decimal:
    """Turn a reservation into the real charge: release the hold, then bill ``actual``.

    The hold guaranteed the funds, so releasing it and charging through the normal
    ``charge_usage`` path (developer -> provider + fee) cannot fail on balance — the whole
    point of reserving. The remainder of the worst case simply stays with the developer once
    the hold is returned. Both postings commit together, so the account is never briefly
    made whole in a way a concurrent request could observe. Returns the amount charged.
    """
    await _return_hold(session, developer_id=developer_id, held=held)
    cost = await charge_usage(
        session,
        developer_id=developer_id,
        provider_id=provider_id,
        cost=actual,
        settings=settings,
    )
    await session.commit()
    return cost


async def release_reservation(
    session: AsyncSession, *, developer_id: uuid.UUID, held: Decimal
) -> None:
    """Return a reservation to the developer in full, charging nothing.

    For the failure paths: no node was reached, or the node failed, so the developer keeps
    every cent. This must commit itself — the request handler re-raises after calling it,
    and ``get_session`` rolls back on the exception, which would otherwise undo the release
    and strand the hold in escrow forever.
    """
    await _return_hold(session, developer_id=developer_id, held=held)
    await session.commit()


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
