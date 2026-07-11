"""Provider reputation — a running score maintained from append-only events.

Every outcome that should shift trust (a clean job, a canary caught cheating, a timeout,
a quorum disagreement) writes a :class:`ReputationEvent` and nudges the provider's score.
The matcher reads the score back (Session 5's reputation-weighted assignment), so honest
work compounds into more work and cheating starves a provider of it.

The score lives in ``[REP_MIN, REP_MAX]``. Canary failure and quorum disagreement carry
the heaviest penalties because they are the clearest signals of cheating.
"""

import uuid

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Provider, ReputationEvent, ReputationKind

REP_MIN = 0.0
REP_MAX = 100.0

# Default score change per event kind.
_DELTAS: dict[ReputationKind, float] = {
    ReputationKind.job_success: 1.0,
    ReputationKind.job_failure: -1.0,
    ReputationKind.timeout: -2.0,
    ReputationKind.canary_pass: 2.0,
    ReputationKind.canary_fail: -25.0,
    ReputationKind.quorum_agree: 1.5,
    ReputationKind.quorum_disagree: -15.0,
    ReputationKind.dispute: -5.0,
    ReputationKind.slash: 0.0,  # economic penalty; reputation moved by the triggering event
}


def _clamp(score: float) -> float:
    return max(REP_MIN, min(REP_MAX, score))


async def record_reputation(
    session: AsyncSession,
    provider: Provider,
    kind: ReputationKind,
    *,
    job_id: uuid.UUID | None = None,
    delta: float | None = None,
    meta: dict | None = None,
) -> ReputationEvent:
    """Apply a reputation event to a provider and persist the audit record.

    Args:
        provider: The provider whose score changes (mutated in place).
        kind: The event kind (drives the default delta).
        job_id: The job this event relates to, if any.
        delta: Override the default delta for ``kind``.
        meta: Optional structured context stored on the event.

    Returns:
        The persisted :class:`ReputationEvent`.
    """
    change = _DELTAS[kind] if delta is None else delta
    provider.reputation = _clamp(provider.reputation + change)
    event = ReputationEvent(
        provider_id=provider.id,
        job_id=job_id,
        kind=kind,
        delta=change,
        score_after=provider.reputation,
        meta=meta,
    )
    session.add(event)
    logger.info(
        "reputation {} {:+.1f} → {:.1f} ({})", provider.id, change, provider.reputation, kind
    )
    return event
