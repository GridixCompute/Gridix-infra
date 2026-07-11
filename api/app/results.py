"""Result intake and finalization — verify, reach quorum, reward or slash.

One provider's result is recorded as an *attempt*. A job finalizes once enough attempts
are in (one for normal jobs, K for redundant high-value jobs): results are verified, a
quorum is taken over their output hashes, the winning result is settled, agreers gain
reputation, and disagreers / caught canary-cheats are slashed. Honest failures lower
reputation but are never slashed — only provable cheating is.
"""

from datetime import UTC, datetime
from decimal import Decimal

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bandwidth import job_bytes
from app.config import Settings
from app.disputes import open_dispute
from app.ledger import LedgerAccount, LedgerDirection, Posting, post_transaction
from app.models import (
    AttemptOutcome,
    Job,
    JobAttempt,
    JobKind,
    JobStatus,
    Provider,
    ReputationKind,
)
from app.payments import get_payment_provider
from app.pricing import compute_cost, data_cost, protocol_fee
from app.quorum import AttemptResult, evaluate_quorum
from app.reputation import record_reputation
from app.schemas import AgentResultRequest
from app.state_machine import TERMINAL_STATES, transition
from app.verification import verify

# Attempt outcome → the reputation event for an honest (non-cheating) result.
_HONEST_REP = {
    AttemptOutcome.completed: ReputationKind.job_success,
    AttemptOutcome.failed: ReputationKind.job_failure,
    AttemptOutcome.timeout: ReputationKind.timeout,
}


def _now() -> datetime:
    return datetime.now(UTC)


async def _attempt_for(session: AsyncSession, job: Job, provider: Provider) -> JobAttempt | None:
    """The provider's in-flight attempt for this job (latest unfinished)."""
    return await session.scalar(
        select(JobAttempt)
        .where(
            JobAttempt.job_id == job.id,
            JobAttempt.provider_id == provider.id,
            JobAttempt.finished_at.is_(None),
        )
        .order_by(JobAttempt.attempt_number.desc())
        .limit(1)
    )


def _attempt_outcome(req: AgentResultRequest, verdict_valid: bool) -> AttemptOutcome:
    if req.timed_out:
        return AttemptOutcome.timeout
    if verdict_valid:
        return AttemptOutcome.completed
    return AttemptOutcome.failed


async def record_result(
    session: AsyncSession,
    job: Job,
    provider: Provider,
    req: AgentResultRequest,
    settings: Settings,
) -> JobStatus:
    """Record one provider's result; finalize the job once enough attempts are in.

    Returns the job's status after this call — terminal once finalized, otherwise the
    still-``running`` status while other redundant attempts are outstanding.
    """
    if job.status is JobStatus.assigned:
        transition(job, JobStatus.running)

    verdict = verify(job, req)
    attempt = await _attempt_for(session, job, provider)
    if attempt is not None:
        attempt.result_ref = req.result_ref
        attempt.proof = req.proof
        attempt.finished_at = _now()
        attempt.outcome = _attempt_outcome(req, verdict.valid)

    # Autoflush is off; make this attempt's completion visible to the count/quorum queries.
    await session.flush()
    finished = await session.scalar(
        select(func.count())
        .select_from(JobAttempt)
        .where(JobAttempt.job_id == job.id, JobAttempt.finished_at.is_not(None))
    )
    if (finished or 0) >= job.redundancy:
        await _finalize(session, job, settings)
    logger.info(
        "recorded result job={} provider={} verdict={} → job status {}",
        job.id,
        provider.id,
        verdict.reason,
        job.status,
    )
    return job.status


async def _finalize(session: AsyncSession, job: Job, settings: Settings) -> None:
    """Take quorum over finished attempts, set the terminal state, reward/slash."""
    if job.status in TERMINAL_STATES:
        return

    attempts = list(
        await session.scalars(
            select(JobAttempt).where(
                JobAttempt.job_id == job.id, JobAttempt.finished_at.is_not(None)
            )
        )
    )
    results = [
        AttemptResult(
            provider_id=str(a.provider_id),
            output_hash=(a.proof or {}).get("output_sha256"),
            succeeded=a.outcome is AttemptOutcome.completed,
        )
        for a in attempts
    ]
    outcome = evaluate_quorum(results, job.redundancy)
    is_canary = job.kind is JobKind.canary
    agreers = set(outcome.agreers)

    winner_provider_id = None
    if outcome.reached:
        winner = next(
            a
            for a in attempts
            if str(a.provider_id) in agreers and a.outcome is AttemptOutcome.completed
        )
        winner_provider_id = winner.provider_id
        job.result_ref = winner.result_ref
        job.proof = winner.proof
        transition(job, JobStatus.completed)
    else:
        # No agreed result. Preserve the timeout distinction when every attempt timed out
        # (e.g. a single job that blew its wall-clock budget); otherwise it is a failure.
        all_timed_out = bool(attempts) and all(
            a.outcome is AttemptOutcome.timeout for a in attempts
        )
        transition(job, JobStatus.timeout if all_timed_out else JobStatus.failed)

    for attempt in attempts:
        provider = await session.get(Provider, attempt.provider_id)
        if provider is None:
            continue
        won = str(attempt.provider_id) in agreers and outcome.reached
        await _apply_outcome(session, job, provider, attempt, won, is_canary, settings, results)

    await _settle(session, job, winner_provider_id, settings)


def _as_utc(dt: datetime) -> datetime:
    """Treat a tz-naive datetime (as SQLite returns) as UTC so arithmetic is safe."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _duration_seconds(job: Job) -> float:
    """Actual run duration, or the timeout budget if timing is unavailable."""
    if job.started_at is not None and job.finished_at is not None:
        return max(0.0, (_as_utc(job.finished_at) - _as_utc(job.started_at)).total_seconds())
    return float(job.timeout_seconds)


async def _settle(session: AsyncSession, job: Job, winner_provider_id, settings: Settings) -> None:
    """Release or refund escrow. Canaries (system-owned, unbilled) are skipped.

    Escrow correctness: on verified completion the developer pays only the actual cost
    (remainder refunded) and the provider is paid net of the protocol fee; on any failure
    the developer is fully refunded and no provider is paid.
    """
    if job.kind is JobKind.canary or job.escrow_amount is None:
        return
    escrow = Decimal(str(job.escrow_amount))
    payment = get_payment_provider()

    if job.status is JobStatus.completed and winner_provider_id is not None:
        cost = min(compute_cost(job.resource_spec or {}, _duration_seconds(job), settings), escrow)
        fee = protocol_fee(cost, settings)
        await payment.settle(session, job.id, job.developer_id, winner_provider_id, cost, fee)
        remainder = escrow - cost
        if remainder > 0:
            await payment.refund(session, job.id, job.developer_id, remainder)
        # Data-movement charge (Session 8.6), billed separately from escrowed compute.
        dcost = data_cost(await job_bytes(session, job.id), settings)
        if dcost > 0:
            await post_transaction(
                session,
                [
                    Posting(
                        LedgerAccount.developer, LedgerDirection.debit, dcost, job.developer_id
                    ),
                    Posting(LedgerAccount.protocol, LedgerDirection.credit, dcost),
                ],
                reason="data_cost",
                job_id=job.id,
            )
        job.cost_final = cost + dcost
    else:
        await payment.refund(session, job.id, job.developer_id, escrow)
        job.cost_final = Decimal(0)


def _slash_evidence(job: Job, attempt: JobAttempt, all_results: list[AttemptResult]) -> dict:
    """Reproducible evidence attached to a slash dispute (Session 10.2).

    Captures everything needed to re-adjudicate: the job identity, the input, the expected
    vs submitted output hashes, the full proof, and — for redundant jobs — every provider's
    quorum vote.
    """
    return {
        "job_id": str(job.id),
        "kind": str(job.kind),
        "input_ref": job.input_ref,
        "expected_output_hash": job.expected_output_hash,
        "submitted_output_hash": (attempt.proof or {}).get("output_sha256"),
        "submitted_result_ref": attempt.result_ref,
        "proof": attempt.proof,
        "attempt_number": attempt.attempt_number,
        "quorum_votes": [
            {"provider_id": r.provider_id, "output_hash": r.output_hash, "succeeded": r.succeeded}
            for r in all_results
        ],
    }


async def _apply_outcome(
    session: AsyncSession,
    job: Job,
    provider: Provider,
    attempt: JobAttempt,
    won: bool,
    is_canary: bool,
    settings: Settings,
    all_results: list[AttemptResult],
) -> None:
    """Move reputation (and stake, when cheating) for one provider's attempt."""
    if won:
        kind = ReputationKind.canary_pass if is_canary else ReputationKind.job_success
        await record_reputation(session, provider, kind, job_id=job.id)
        if job.redundancy > 1:
            await record_reputation(session, provider, ReputationKind.quorum_agree, job_id=job.id)
        return

    # Did not win. A canary miss or a quorum dissent is cheating → slash. An honest
    # standalone failure is not. Slashes are HELD via a dispute, not burned (Session 10.1).
    if is_canary:
        await record_reputation(session, provider, ReputationKind.canary_fail, job_id=job.id)
        await open_dispute(
            session,
            provider.id,
            Decimal(settings.slash_amount),
            reason="canary_fail",
            settings=settings,
            job_id=job.id,
            evidence=_slash_evidence(job, attempt, all_results),
        )
    elif job.redundancy > 1 and attempt.outcome is AttemptOutcome.completed:
        await record_reputation(session, provider, ReputationKind.quorum_disagree, job_id=job.id)
        await open_dispute(
            session,
            provider.id,
            Decimal(settings.slash_amount),
            reason="quorum_disagree",
            settings=settings,
            job_id=job.id,
            evidence=_slash_evidence(job, attempt, all_results),
        )
    else:
        await record_reputation(
            session,
            provider,
            _HONEST_REP.get(attempt.outcome, ReputationKind.job_failure),
            job_id=job.id,
        )
