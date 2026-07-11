"""Session 5 — verification, reputation, ledger stake/slash, quorum, and matching."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job, assign_providers
from app.canary import CANARY_EXPECTED_HASH, create_canary_job
from app.ledger import (
    Posting,
    UnbalancedTransactionError,
    account_balance,
    deposit_stake,
    post_transaction,
    provider_stake,
    slash_stake,
)
from app.matcher import CapabilityMatcher, ReputationMatcher, set_matcher
from app.models import (
    Job,
    JobKind,
    JobStatus,
    LedgerAccount,
    LedgerDirection,
    Provider,
    ReputationKind,
)
from app.quorum import AttemptResult, evaluate_quorum
from app.reputation import REP_MAX, record_reputation
from app.results import record_result
from app.schemas import AgentResultRequest
from app.verification import verify
from conftest import make_provider, register
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


@pytest.fixture(autouse=True)
def _reputation_matcher():
    """Session 5 uses the reputation-weighted, stake-gated matcher."""
    set_matcher(ReputationMatcher())
    yield
    set_matcher(CapabilityMatcher())


def _result(
    *, hash_: str | None, exit_code: int = 0, timed_out: bool = False
) -> AgentResultRequest:
    proof = {"exit_code": exit_code}
    if hash_ is not None:
        proof["output_sha256"] = hash_
    return AgentResultRequest(
        result_ref=hash_, exit_code=exit_code, proof=proof, timed_out=timed_out
    )


# ── verify() ────────────────────────────────────────────────────────────────────
def test_verify_standard_and_failure_paths() -> None:
    job = Job(image_ref="i", kind=JobKind.standard, resource_spec={})
    assert verify(job, _result(hash_="abc")).valid
    assert not verify(job, _result(hash_="abc", exit_code=1)).valid
    assert not verify(job, _result(hash_="abc", timed_out=True)).valid
    # Malformed: result claimed but no output hash.
    bad = AgentResultRequest(result_ref="x", exit_code=0, proof={"exit_code": 0})
    assert not verify(job, bad).valid


def test_verify_canary_match() -> None:
    job = Job(
        image_ref="i",
        kind=JobKind.canary,
        resource_spec={},
        expected_output_hash=CANARY_EXPECTED_HASH,
    )
    good = verify(job, _result(hash_=CANARY_EXPECTED_HASH))
    assert good.valid and good.is_canary and good.canary_passed
    bad = verify(job, _result(hash_="deadbeef"))
    assert not bad.valid and bad.canary_passed is False


# ── quorum ──────────────────────────────────────────────────────────────────────
def test_quorum_majority_and_dissent() -> None:
    attempts = [
        AttemptResult("p1", "A", True),
        AttemptResult("p2", "A", True),
        AttemptResult("p3", "B", True),
    ]
    out = evaluate_quorum(attempts, redundancy=3)
    assert out.reached and out.winning_hash == "A"
    assert set(out.agreers) == {"p1", "p2"} and out.disagreers == ["p3"]


def test_quorum_no_majority_is_inconclusive() -> None:
    attempts = [AttemptResult("p1", "A", True), AttemptResult("p2", "B", True)]
    assert not evaluate_quorum(attempts, redundancy=2).reached


def test_quorum_single_vote() -> None:
    out = evaluate_quorum([AttemptResult("p1", "A", True)], redundancy=1)
    assert out.reached and out.agreers == ["p1"]


# ── reputation ──────────────────────────────────────────────────────────────────
async def test_reputation_moves_and_clamps(session) -> None:
    provider = Provider(name="p", reputation=REP_MAX - 0.5)
    session.add(provider)
    await session.flush()
    await record_reputation(session, provider, ReputationKind.job_success)
    assert provider.reputation == REP_MAX  # clamped
    await record_reputation(session, provider, ReputationKind.canary_fail)
    assert provider.reputation == REP_MAX - 25.0


# ── ledger ──────────────────────────────────────────────────────────────────────
async def test_ledger_balanced_and_stake(session) -> None:
    pid = uuid.uuid4()
    await deposit_stake(session, pid, Decimal(100))
    assert await provider_stake(session, pid) == Decimal(100)

    slashed = await slash_stake(session, pid, Decimal(60))
    assert slashed == Decimal(60)
    assert await provider_stake(session, pid) == Decimal(40)
    # Slash is capped at the remaining balance.
    assert await slash_stake(session, pid, Decimal(100)) == Decimal(40)
    assert await provider_stake(session, pid) == Decimal(0)


async def test_ledger_rejects_unbalanced(session) -> None:
    with pytest.raises(UnbalancedTransactionError):
        await post_transaction(
            session,
            [Posting(LedgerAccount.protocol, LedgerDirection.debit, Decimal(10))],
            reason="oops",
        )
    assert await account_balance(session, LedgerAccount.protocol) == Decimal(0)


# ── integration: canary cheat → slash → starved ─────────────────────────────────
async def test_canary_failure_slashes_and_starves_provider(
    client: AsyncClient, session, settings
) -> None:
    """A provider that fails a canary loses reputation and stake, then gets no work."""
    pid, _ = await make_provider(client, "cheat", cpu_cores=8, memory_mb=16000)
    await deposit_stake(session, uuid.UUID(pid), Decimal(settings.min_provider_stake))
    await session.commit()

    canary = await create_canary_job(session)
    await session.commit()
    await assign_job(session, canary.id, settings)

    job = await session.get(Job, canary.id)
    provider = await session.get(Provider, uuid.UUID(pid))
    rep_before = provider.reputation

    # Provider returns the wrong answer for the canary.
    final = await record_result(session, job, provider, _result(hash_="deadbeef"), settings)
    await session.commit()

    assert final is JobStatus.failed
    assert provider.reputation < rep_before
    assert await provider_stake(session, uuid.UUID(pid)) < settings.min_provider_stake

    # Below min stake → the matcher will not assign it new work.
    new_job = Job(
        developer_id=job.developer_id,
        image_ref="img",
        resource_spec={"cpu_cores": 1, "memory_mb": 1000},
    )
    session.add(new_job)
    await session.flush()
    assert await ReputationMatcher().select(session, new_job) is None


# ── integration: reputation changes who is matched ──────────────────────────────
async def test_higher_reputation_provider_is_preferred(
    client: AsyncClient, session, settings
) -> None:
    hi, _ = await make_provider(client, "hi", cpu_cores=8, memory_mb=16000)
    lo, _ = await make_provider(client, "lo", cpu_cores=8, memory_mb=16000)
    for p in (hi, lo):
        await deposit_stake(session, uuid.UUID(p), Decimal(settings.min_provider_stake))
    hi_provider = await session.get(Provider, uuid.UUID(hi))
    hi_provider.reputation = 95.0
    await session.commit()

    job = Job(
        developer_id=uuid.uuid4(),
        image_ref="img",
        resource_spec={"cpu_cores": 1, "memory_mb": 1000},
    )
    chosen = await ReputationMatcher().select(session, job)
    assert chosen is not None and str(chosen.id) == hi


# ── integration: redundant quorum settles majority, slashes dissenter ───────────
async def test_redundant_quorum_slashes_dissenter(client: AsyncClient, session, settings) -> None:
    """A high-value job on 3 providers: the 2 that agree win, the odd one out is slashed."""
    # All client (HTTP) writes first, then the session-driven work — interleaving the
    # two SQLite connections with an open transaction would deadlock.
    ids = []
    for name in ("a", "b", "c"):
        pid, _ = await make_provider(client, name, cpu_cores=8, memory_mb=16000)
        ids.append(pid)
    _dev, dev_key = await register(client, "developer", "Acme")
    r = await client.post(
        "/jobs",
        headers={"Authorization": f"Bearer {dev_key}"},
        json={
            "image_ref": "img",
            "is_high_value": True,
            "redundancy": 3,
            "resource_spec": {"cpu_cores": 1, "memory_mb": 1000},
        },
    )
    job_id = uuid.UUID(r.json()["id"])

    for pid in ids:
        await deposit_stake(session, uuid.UUID(pid), Decimal(settings.min_provider_stake))
        # High-value work requires reputation above the floor.
        p = await session.get(Provider, uuid.UUID(pid))
        p.reputation = 85.0
    await session.commit()

    providers = await assign_providers(session, job_id, settings)
    assert len(providers) == 3

    job = await session.get(Job, job_id)
    # Two providers agree on "AAA"; one dissents with "BBB".
    votes = {str(providers[0].id): "AAA", str(providers[1].id): "AAA", str(providers[2].id): "BBB"}
    dissenter = providers[2]
    for provider in providers:
        p = await session.get(Provider, provider.id)
        await record_result(session, job, p, _result(hash_=votes[str(provider.id)]), settings)
    await session.commit()

    final = await session.get(Job, job_id)
    assert final.status is JobStatus.completed
    assert final.proof["output_sha256"] == "AAA"
    # The dissenter was slashed below the others.
    assert await provider_stake(session, dissenter.id) < settings.min_provider_stake
