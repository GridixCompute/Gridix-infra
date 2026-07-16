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
from app.fraud_proof import evidence_commitment
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
        evidence_hash=evidence_commitment(evidence) if evidence is not None else None,
        window_expires_at=_now() + timedelta(seconds=settings.dispute_window_seconds),
    )
    session.add(dispute)
    await session.flush()
    logger.info(
        "dispute {} opened: provider {} held {} ({})", dispute.id, provider_id, held, reason
    )
    return dispute


def _window_open(dispute: Dispute) -> bool:
    """True while the dispute's contest window is still running.

    A dispute with no window is treated as CLOSED: we cannot demonstrate the window is
    open, so we refuse rather than hand out an unbounded right to contest (fail closed).
    """
    expires = dispute.window_expires_at
    if expires is None:
        return False
    if expires.tzinfo is None:
        # SQLite returns naive datetimes for DateTime(timezone=True); they are stored UTC.
        expires = expires.replace(tzinfo=UTC)
    return _now() < expires


async def contest_dispute(session: AsyncSession, dispute: Dispute) -> bool:
    """Provider contests an open slash → ``under_review`` (awaiting adjudication).

    Returns False and changes nothing when the dispute is not open or its contest window
    has closed. The window check is what lets an unanswered slash auto-confirm: without it
    a provider could contest a long-expired dispute forever, parking the held stake in
    limbo and breaking dispute resolution economically (pentest H6). Enforced here rather
    than at the route so every caller inherits it.
    """
    if dispute.state is not DisputeState.open or not _window_open(dispute):
        return False
    dispute.state = DisputeState.under_review
    return True


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
