"""Automated dispute adjudication (Session 10.3).

First-line adjudication re-checks a disputed result against the known-good answer — the
canary's expected output, or a redundant job's quorum majority — both captured in the
dispute evidence (10.2). A clearly-wrong result auto-upholds the slash; a clearly-correct
one auto-overturns it (the slash was a mistake). Anything ambiguous escalates to human
review (10.4) rather than guessing.
"""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.disputes import resolve_dispute
from app.models import AttemptOutcome, Dispute, DisputeState, Job, JobAttempt
from app.quorum import AttemptResult, evaluate_quorum


def _known_good(evidence: dict) -> str | None:
    """The expected output hash for the dispute, or None if it can't be determined."""
    if evidence.get("expected_output_hash"):
        return evidence["expected_output_hash"]  # canary: coordinator knows the answer
    # Redundant job: the quorum majority is the reference truth.
    votes = evidence.get("quorum_votes") or []
    hashes = [v["output_hash"] for v in votes if v.get("succeeded") and v.get("output_hash")]
    if not hashes:
        return None
    winner, count = Counter(hashes).most_common(1)[0]
    return winner if count >= (len(votes) // 2 + 1) else None


async def auto_adjudicate(
    session: AsyncSession, dispute: Dispute, settings: Settings
) -> DisputeState | None:
    """Try to resolve a dispute automatically; return the terminal state, or None if it
    escalated to human review (10.4)."""
    evidence = dispute.evidence or {}
    submitted = evidence.get("submitted_output_hash")
    expected = _known_good(evidence)

    if expected is None or submitted is None:
        dispute.state = DisputeState.under_review  # can't decide → escalate
        return None

    if submitted == expected:
        await resolve_dispute(
            session, dispute, upheld=False, ruling_reason="auto: matches known-good output"
        )
        return DisputeState.overturned

    await resolve_dispute(
        session, dispute, upheld=True, ruling_reason="auto: differs from known-good output"
    )
    return DisputeState.upheld


async def quorum_revote(
    session: AsyncSession, dispute: Dispute, settings: Settings
) -> DisputeState | None:
    """Re-collect a redundant job's K results from the DB and settle the dispute by
    majority (Session 10.5).

    The disputing provider's output is compared to the freshly-recomputed quorum winner:
    matching the majority overturns the slash, disagreeing upholds it. A job with no clear
    majority escalates to human review.
    """
    if dispute.job_id is None:
        dispute.state = DisputeState.under_review
        return None
    job = await session.get(Job, dispute.job_id)
    attempts = list(
        await session.scalars(select(JobAttempt).where(JobAttempt.job_id == dispute.job_id))
    )
    results = [
        AttemptResult(
            provider_id=str(a.provider_id),
            output_hash=(a.proof or {}).get("output_sha256"),
            succeeded=a.outcome is AttemptOutcome.completed,
        )
        for a in attempts
    ]
    outcome = evaluate_quorum(results, job.redundancy if job else len(results))
    if not outcome.reached:
        dispute.state = DisputeState.under_review
        return None

    submitted = next(
        (
            (a.proof or {}).get("output_sha256")
            for a in attempts
            if a.provider_id == dispute.provider_id
        ),
        None,
    )
    upheld = submitted != outcome.winning_hash
    await resolve_dispute(
        session,
        dispute,
        upheld=upheld,
        ruling_reason=f"revote: majority={outcome.winning_hash[:12]}",
    )
    return DisputeState.upheld if upheld else DisputeState.overturned
