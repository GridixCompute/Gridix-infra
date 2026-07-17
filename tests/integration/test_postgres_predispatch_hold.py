"""The pre-dispatch reservation is atomic — proven on real PostgreSQL.

This is the fix for the B2 finding: ``assert_can_afford`` was a bare balance read with no
reservation, so two concurrent requests from one developer with balance for one both passed
the gate and both dispatched — burning a provider's GPU on the request that could not be
paid for. ``reserve_balance`` now locks the developer row and holds the worst case before a
node is touched, so the second request is refused AT THE GATE, before any dispatch.

Like test_postgres_overdraw, this cannot be proven on SQLite: the guarantee is that two
concurrent balance reads serialise, and SQLite ignores ``SELECT ... FOR UPDATE`` (its
database-wide write lock does not order the reads the way row locking does). So this file
runs against Postgres or not at all.

    GRIDIX_TEST_POSTGRES_URL=postgresql+asyncpg://user:pass@host/db pytest tests/integration

Locally that is optional and these skip. In CI it is not (see the skipif below): the whole
point of the fix is a lock that only a real database enforces, so CI must actually run it.

Forcing the interleaving. ``reserve_balance`` reads, posts, and commits in a tight sequence,
so asyncio would run one reservation to completion before the next even reads — the bug the
lock prevents (both reading the full balance at once) would never occur naturally, and the
test could not tell a locked build from an unlocked one. The ``overlapping_reads`` fixture
holds each reservation's transaction open for a beat between its read and its post, which is
exactly the window a bare read leaves. WITH the lock the second reservation blocks on
``FOR UPDATE`` and never reaches that window, so it still sees the committed hold and is
refused; WITHOUT it both read the full balance in the window and both dispatch. That is what
makes the mutation test below bite: pull the lock and these go red.
"""

import asyncio
import os
import uuid
from decimal import Decimal

import pytest
from app.config import get_settings
from app.db import Base
from app.models import Developer, LedgerAccount, Provider
from app.usage_billing import (
    InsufficientBalanceError,
    credit_deposit,
    developer_balance,
    reserve_balance,
    settle_reservation,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

POSTGRES_URL = os.getenv("GRIDIX_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL and not os.getenv("CI"),
    reason=(
        "needs a real PostgreSQL (SQLite ignores FOR UPDATE, so the reservation lock cannot "
        "be tested there). Set GRIDIX_TEST_POSTGRES_URL to run it."
    ),
)

_READ_HOLD_SECONDS = 0.25


@pytest.fixture
def overlapping_reads(monkeypatch):
    """Hold each reservation's transaction open between its balance read and its post.

    This is the window a lock-free gate leaves and a lock closes. It does NOT weaken the
    guarantee under test: with the lock, a second reservation blocks on ``FOR UPDATE``
    before it can reach this window, so the delay only makes the *unlocked* race observable
    and deterministic. See the module docstring.
    """
    import app.usage_billing as ub

    real = developer_balance

    async def slow_read(session, dev_id):
        balance = await real(session, dev_id)
        await asyncio.sleep(_READ_HOLD_SECONDS)
        return balance

    monkeypatch.setattr(ub, "developer_balance", slow_read)
    return None


@pytest.fixture
async def pg():
    """A real Postgres engine with the schema, torn down after."""
    engine = create_async_engine(POSTGRES_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def funded(pg):
    """A developer holding exactly 1.00 USDC — enough for one worst_case — and two nodes."""
    maker = async_sessionmaker(pg, expire_on_commit=False)
    dev_id, provider_ids = uuid.uuid4(), [uuid.uuid4(), uuid.uuid4()]
    async with maker() as s:
        s.add(Developer(id=dev_id, name="Acme"))
        for pid in provider_ids:
            s.add(Provider(id=pid, name=f"node-{pid.hex[:4]}"))
        await s.flush()
        await credit_deposit(s, developer_id=dev_id, amount=Decimal("1.00"))
        await s.commit()
    return maker, dev_id, provider_ids


async def _gate_then_serve(maker, dev_id, provider_id, dispatched: list) -> str:
    """One request's money flow in its own transaction, exactly as the route runs it.

    Reserve the worst case (the gate). If it is refused, the request 402s and NO node is
    touched. If it is granted, the node's GPU runs (recorded in ``dispatched``) and the
    reservation is settled at the actual cost.
    """
    worst_case, actual = Decimal("1.00"), Decimal("0.40")
    async with maker() as session:
        try:
            held = await reserve_balance(session, developer_id=dev_id, amount=worst_case)
        except InsufficientBalanceError:
            return "refused_at_gate"  # 402, before any dispatch
        # Gate passed → the provider's GPU runs. This is the line that must happen at most
        # once for a balance that covers one request.
        dispatched.append(provider_id)
        await settle_reservation(
            session,
            developer_id=dev_id,
            provider_id=provider_id,
            held=held,
            actual=actual,
            settings=get_settings(),
        )
        return "served"


async def _balance(maker, dev_id) -> Decimal:
    async with maker() as s:
        return await developer_balance(s, dev_id)


class TestPreDispatchHold:
    async def test_only_one_of_two_concurrent_requests_reaches_a_node(
        self, funded, overlapping_reads
    ) -> None:
        """The case the reservation exists for: balance covers one, two arrive at once.

        Without a hold both read 1.00, both pass the gate, and both dispatch — a provider
        burns a GPU on the request that ends up unpaid. With it, the second sees the first's
        hold and is refused before a node is touched.

        Mutation guard: delete the FOR UPDATE lock in reserve_balance and both dispatch on
        Postgres — this goes red.
        """
        maker, dev_id, (p1, p2) = funded
        dispatched: list = []

        results = await asyncio.gather(
            _gate_then_serve(maker, dev_id, p1, dispatched),
            _gate_then_serve(maker, dev_id, p2, dispatched),
        )

        # Exactly one node's GPU ran. This is the whole finding: never burn a provider's GPU
        # for a request that cannot be paid for.
        assert len(dispatched) == 1, (
            f"expected 1 dispatch on a 1-request balance, got {len(dispatched)}"
        )
        assert sorted(results) == ["refused_at_gate", "served"]
        # The developer paid the one actual cost (0.40) and was not overdrawn.
        assert await _balance(maker, dev_id) == Decimal("0.60")

    async def test_the_refused_request_pays_nothing_and_the_hold_nets_out(
        self, funded, overlapping_reads
    ) -> None:
        """After the race, escrow is empty and the ledger balances — no hold left stranded."""
        from app.ledger import account_balance, verify_ledger_integrity

        maker, dev_id, (p1, p2) = funded
        dispatched: list = []
        await asyncio.gather(
            _gate_then_serve(maker, dev_id, p1, dispatched),
            _gate_then_serve(maker, dev_id, p2, dispatched),
        )
        async with maker() as s:
            assert await verify_ledger_integrity(s) == []
            # Every reservation was either settled or released, so nothing sits in escrow.
            assert await account_balance(s, LedgerAccount.escrow, dev_id) == Decimal("0")

    async def test_a_burst_never_dispatches_more_than_the_balance_can_pay(
        self, funded, overlapping_reads
    ) -> None:
        """Eight at once on a balance for one: at most one node is ever touched."""
        maker, dev_id, (p1, _p2) = funded
        dispatched: list = []

        await asyncio.gather(*(_gate_then_serve(maker, dev_id, p1, dispatched) for _ in range(8)))

        assert len(dispatched) == 1, f"expected 1 of 8 to dispatch, got {len(dispatched)}"
        assert await _balance(maker, dev_id) == Decimal("0.60")
