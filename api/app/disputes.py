"""Dispute lifecycle & slashing governance (Session 10).

A slash no longer burns stake immediately. Instead the amount is *held* in the
``disputed`` ledger account and a :class:`Dispute` opens: the provider can contest within a
window (``open → under_review``), and adjudication either upholds the slash (held → burned
to protocol) or overturns it (held → returned to the provider's stake). This makes slashing
fair, so honest providers hit by a bad canary/quorum call don't quit.

Both money invariants hold: held stake is never lost or double-counted, and every dispute
ends in a terminal state (``upheld``/``overturned``).
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ledger import LedgerAccount, LedgerDirection, Posting, post_transaction, provider_stake
from app.models import Dispute, DisputeState


def _now() -> datetime:
    return datetime.now(UTC)


async def open_dispute(
    session: AsyncSession,
    provider_id: uuid.UUID,
    amount: Decimal,
    *,
    reason: str,
    settings: Settings,
    job_id: uuid.UUID | None = None,
    evidence: dict | None = None,
) -> Dispute:
    """Slash-and-hold: move up to ``amount`` of stake into ``disputed`` and open a dispute.

    The held amount is capped at the provider's current stake so stake never goes negative.
    Returns the created (open) dispute.
    """
    current = await provider_stake(session, provider_id)
    held = min(amount, current)
    if held > 0:
        await post_transaction(
            session,
            [
                Posting(LedgerAccount.stake, LedgerDirection.debit, held, provider_id),
                Posting(LedgerAccount.disputed, LedgerDirection.credit, held, provider_id),
            ],
            reason="slash_hold",
            job_id=job_id,
        )
    dispute = Dispute(
        provider_id=provider_id,
        job_id=job_id,
        amount=held,
        state=DisputeState.open,
        reason=reason,
        evidence=evidence,
        window_expires_at=_now() + timedelta(seconds=settings.dispute_window_seconds),
    )
    session.add(dispute)
    await session.flush()
    logger.info(
        "dispute {} opened: provider {} held {} ({})", dispute.id, provider_id, held, reason
    )
    return dispute


async def contest_dispute(session: AsyncSession, dispute: Dispute) -> None:
    """Provider contests an open slash → ``under_review`` (awaiting adjudication)."""
    if dispute.state is DisputeState.open:
        dispute.state = DisputeState.under_review


async def resolve_dispute(
    session: AsyncSession, dispute: Dispute, *, upheld: bool, ruling_reason: str = ""
) -> None:
    """Settle a dispute: burn the held stake (upheld) or return it (overturned)."""
    if dispute.state in (DisputeState.upheld, DisputeState.overturned):
        return  # already terminal
    amount = Decimal(str(dispute.amount))
    if amount > 0:
        credit = LedgerAccount.protocol if upheld else LedgerAccount.stake
        ref = None if upheld else dispute.provider_id
        await post_transaction(
            session,
            [
                Posting(LedgerAccount.disputed, LedgerDirection.debit, amount, dispute.provider_id),
                Posting(credit, LedgerDirection.credit, amount, ref),
            ],
            reason="slash_confirmed" if upheld else "slash_reversed",
            job_id=dispute.job_id,
        )
    dispute.state = DisputeState.upheld if upheld else DisputeState.overturned
    dispute.ruling_reason = ruling_reason or dispute.ruling_reason
    dispute.resolved_at = _now()
    logger.info("dispute {} resolved: {}", dispute.id, dispute.state)
