"""Graduated penalties (Session 10.6).

A single-cliff slash punishes a one-off hardware flake the same as deliberate cheating,
which drives honest providers away. Instead:

* **Honest failures** (timeout, plain job failure) are never slashed — only a small
  reputation decay (handled in ``results``).
* **Adversarial offenses** (canary fail, quorum disagreement) are slashed, and the amount
  *escalates* with the provider's history of upheld disputes — a first offense stings, a
  repeat offender is hit progressively harder (capped).
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dispute, DisputeState

# Escalation is doubled per prior upheld offense, capped so it can't run away.
_MAX_MULTIPLIER = 8


async def count_prior_offenses(session: AsyncSession, provider_id) -> int:
    """Number of the provider's previously *upheld* slash disputes (proven offenses)."""
    total = await session.scalar(
        select(func.count())
        .select_from(Dispute)
        .where(Dispute.provider_id == provider_id, Dispute.state == DisputeState.upheld)
    )
    return int(total or 0)


def graduated_slash(base: Decimal, prior_upheld: int) -> Decimal:
    """The slash amount for an adversarial offense given the provider's prior offenses.

    ``base`` for a first offense, doubling per prior upheld offense up to the cap.
    """
    multiplier = min(2**prior_upheld, _MAX_MULTIPLIER)
    return base * Decimal(multiplier)
