"""Concurrent charges cannot overdraw a balance — proven on real PostgreSQL.

This cannot be proven on SQLite. ``charge_usage`` serialises concurrent charges for one
developer with ``SELECT ... FOR UPDATE``; SQLite parses that and ignores it, and its
database-wide write lock hides the difference by serialising everything anyway. A suite
that only runs on SQLite would pass with the lock deleted.

So this file runs against Postgres or not at all. Point it at one with:

    GRIDIX_TEST_POSTGRES_URL=postgresql+asyncpg://user:pass@host/db pytest tests/integration

Locally that is optional and these skip. In CI it is not: see the skipif below.
"""

import asyncio
import os
import uuid
from decimal import Decimal

import pytest
from app.config import get_settings
from app.db import Base
from app.models import Developer, Provider
from app.usage_billing import InsufficientBalanceError, charge_usage, credit_deposit
from conftest import wallet_address
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

POSTGRES_URL = os.getenv("GRIDIX_TEST_POSTGRES_URL")

# Skipping locally is a convenience; skipping in CI would be a hole. A skip is silent and
# reads as success, so if the service is ever misconfigured these tests would quietly stop
# running and the overdraw guard would stop being checked with nothing to say so. In CI
# they run regardless and fail loudly on a missing database.
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL and not os.getenv("CI"),
    reason=(
        "needs a real PostgreSQL (SQLite ignores FOR UPDATE, so the lock cannot be tested "
        "there). Set GRIDIX_TEST_POSTGRES_URL to run it."
    ),
)


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
    """A developer holding exactly 1.00 USDC, and two nodes to pay."""
    maker = async_sessionmaker(pg, expire_on_commit=False)
    dev_id, provider_ids = uuid.uuid4(), [uuid.uuid4(), uuid.uuid4()]
    async with maker() as s:
        s.add(Developer(id=dev_id, name="Acme"))
        for pid in provider_ids:
            s.add(Provider(id=pid, name=f"node-{pid.hex[:4]}", wallet_address=wallet_address()))
        await s.flush()
        await credit_deposit(s, developer_id=dev_id, amount=Decimal("1.00"))
        await s.commit()
    return maker, dev_id, provider_ids


async def _charge_in_own_transaction(maker, dev_id, provider_id, amount: Decimal) -> str:
    """One charge in its own session/transaction, as two concurrent requests would be."""
    async with maker() as session:
        try:
            await charge_usage(
                session,
                developer_id=dev_id,
                provider_id=provider_id,
                cost=amount,
                settings=get_settings(),
            )
            await session.commit()
            return "charged"
        except InsufficientBalanceError:
            await session.rollback()
            return "refused"


async def _balance(maker, dev_id) -> Decimal:
    from app.usage_billing import developer_balance

    async with maker() as s:
        return await developer_balance(s, dev_id)


class TestConcurrentOverdraw:
    async def test_two_concurrent_charges_only_one_wins(self, funded) -> None:
        """The case the lock exists for: balance covers one, two arrive at once.

        Without serialisation both read 1.00, both see enough, both post — and the
        developer has bought 2.00 of compute with 1.00.
        """
        maker, dev_id, (p1, p2) = funded

        results = await asyncio.gather(
            _charge_in_own_transaction(maker, dev_id, p1, Decimal("1.00")),
            _charge_in_own_transaction(maker, dev_id, p2, Decimal("1.00")),
        )

        assert sorted(results) == ["charged", "refused"]
        assert await _balance(maker, dev_id) == Decimal("0.00")

    async def test_the_balance_never_goes_negative_under_a_burst(self, funded) -> None:
        """Eight at once, each for a third of the balance: at most three can land."""
        maker, dev_id, (p1, _p2) = funded

        results = await asyncio.gather(
            *(_charge_in_own_transaction(maker, dev_id, p1, Decimal("0.33")) for _ in range(8))
        )

        charged = results.count("charged")
        balance = await _balance(maker, dev_id)
        assert charged == 3, f"expected 3 of 8 to fit in 1.00, got {charged}"
        assert balance >= Decimal("0"), f"balance went negative: {balance}"
        assert balance == Decimal("1.00") - Decimal("0.33") * charged

    async def test_charges_for_different_developers_do_not_block_each_other(self, pg) -> None:
        """The lock is per developer, not a global mutex: two developers proceed together."""
        maker = async_sessionmaker(pg, expire_on_commit=False)
        a, b, provider = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with maker() as s:
            s.add_all([Developer(id=a, name="A"), Developer(id=b, name="B")])
            s.add(Provider(id=provider, name="node", wallet_address=wallet_address()))
            await s.flush()
            await credit_deposit(s, developer_id=a, amount=Decimal("1.00"))
            await credit_deposit(s, developer_id=b, amount=Decimal("1.00"))
            await s.commit()

        results = await asyncio.gather(
            _charge_in_own_transaction(maker, a, provider, Decimal("1.00")),
            _charge_in_own_transaction(maker, b, provider, Decimal("1.00")),
        )
        assert results == ["charged", "charged"]
        assert await _balance(maker, a) == Decimal("0.00")
        assert await _balance(maker, b) == Decimal("0.00")

    async def test_the_ledger_stays_balanced_after_the_race(self, funded) -> None:
        """Whatever the race decides, the invariant holds: every group nets to zero."""
        from app.ledger import verify_ledger_integrity

        maker, dev_id, (p1, p2) = funded
        await asyncio.gather(
            _charge_in_own_transaction(maker, dev_id, p1, Decimal("1.00")),
            _charge_in_own_transaction(maker, dev_id, p2, Decimal("1.00")),
        )
        async with maker() as s:
            assert await verify_ledger_integrity(s) == []
