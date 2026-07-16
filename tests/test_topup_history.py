"""A top-up can be traced back to the transaction that made it.

Driven through the real ChainWatcher against the in-memory FakeChain: a deposit is
emitted on-chain, confirmed, ingested, and then read back off /billing/ledger the way the
frontend will. Both halves matter and neither is enough alone — the watcher has to carry
tx_hash into the ledger, and the endpoint has to return deposit rows at all.
"""

import uuid
from decimal import Decimal

import pytest
from app.chain.bootstrap import install_chain_client
from app.chain.fake import FakeChain
from app.chain.registry import set_chain_client
from app.chain.watcher import ChainWatcher
from app.config import get_settings
from app.db import get_sessionmaker
from app.models import Developer, LedgerEntry
from app.payments import get_payment_provider, set_payment_provider
from conftest import auth, register
from httpx import AsyncClient
from sqlalchemy import select

USDC = 10**6
CONF = 3


def wallet(seed: str) -> str:
    return "0x" + (seed * 40)[:40]


def _watcher(fc: FakeChain) -> ChainWatcher:
    return ChainWatcher(fc, get_sessionmaker(), usdc_decimals=6, confirmations=CONF)


async def _link_wallet(dev_id: str, addr: str) -> None:
    async with get_sessionmaker()() as s:
        dev = await s.get(Developer, uuid.UUID(dev_id))
        dev.wallet_address = addr
        await s.commit()


async def _deposit(fc: FakeChain, addr: str, amount_usdc: int) -> str:
    """Deposit on-chain, confirm it, and let the watcher ingest it. Returns the tx hash."""
    tx = fc.external_deposit(addr, amount_usdc * USDC)
    fc.mine(CONF)
    await _watcher(fc).tick()
    return tx


@pytest.fixture
def restore_chain():
    """Save/restore the process-global payment provider + chain client around a test.

    install_chain_client mutates module-level state; without this a fake chain leaks into
    whatever runs next.
    """
    saved = get_payment_provider()
    yield
    set_payment_provider(saved)
    set_chain_client(None)


@pytest.fixture
async def funded_developer(client: AsyncClient, restore_chain):
    """A developer with a linked wallet and a live fake chain."""
    dev_id, dev_key = await register(client, "developer", "Acme")
    addr = wallet("a")
    await _link_wallet(dev_id, addr)
    fc = FakeChain()
    install_chain_client(get_settings(), fc)
    return dev_id, dev_key, addr, fc


class TestWatcherRecordsTheTransaction:
    async def test_a_deposit_lands_in_the_ledger_with_its_tx_hash(
        self, funded_developer, session
    ) -> None:
        _dev_id, _key, addr, fc = funded_developer
        tx = await _deposit(fc, addr, 50)

        rows = (
            await session.scalars(select(LedgerEntry).where(LedgerEntry.reason == "chain_deposit"))
        ).all()
        assert rows, "the watcher credited nothing"
        assert {r.tx_hash for r in rows} == {tx}

    async def test_every_leg_of_the_group_carries_it(self, funded_developer, session) -> None:
        """The transaction caused the whole group, not just the developer's side."""
        _dev_id, _key, addr, fc = funded_developer
        tx = await _deposit(fc, addr, 50)

        rows = (
            await session.scalars(select(LedgerEntry).where(LedgerEntry.reason == "chain_deposit"))
        ).all()
        assert len(rows) == 2  # protocol debit + developer credit
        assert all(r.tx_hash == tx for r in rows)

    async def test_two_deposits_keep_their_own_hashes(self, funded_developer, session) -> None:
        _dev_id, _key, addr, fc = funded_developer
        first = await _deposit(fc, addr, 10)
        second = await _deposit(fc, addr, 20)

        assert first != second
        rows = (
            await session.scalars(select(LedgerEntry).where(LedgerEntry.reason == "chain_deposit"))
        ).all()
        assert {r.tx_hash for r in rows} == {first, second}

    async def test_movements_with_no_transaction_have_no_hash(
        self, funded_developer, session
    ) -> None:
        """Null is the honest answer for an inference charge or a fee — inventing one
        would put a link in the UI that goes nowhere."""
        from app.models import Provider
        from app.usage_billing import charge_usage

        dev_id, _key, addr, fc = funded_developer
        await _deposit(fc, addr, 50)

        provider = Provider(name="node")
        session.add(provider)
        await session.flush()
        await charge_usage(
            session,
            developer_id=uuid.UUID(dev_id),
            provider_id=provider.id,
            cost=Decimal("1"),
            settings=get_settings(),
        )
        await session.commit()

        charges = (
            await session.scalars(
                select(LedgerEntry).where(LedgerEntry.reason == "inference_usage")
            )
        ).all()
        assert charges and all(r.tx_hash is None for r in charges)


class TestBillingShowsTopUps:
    async def test_the_statement_includes_the_deposit_and_its_hash(
        self, funded_developer, client: AsyncClient
    ) -> None:
        """The endpoint used to inner-join jobs, so deposits — which have no job — never
        appeared at all. A developer saw their balance rise with nothing to explain it."""
        _dev_id, key, addr, fc = funded_developer
        tx = await _deposit(fc, addr, 50)

        res = await client.get("/billing/ledger", headers=auth(key))
        assert res.status_code == 200
        deposits = [r for r in res.json() if r["reason"] == "chain_deposit"]
        assert deposits, "the top-up is missing from the statement"
        assert all(d["tx_hash"] == tx for d in deposits)

    async def test_the_developers_own_credit_leg_is_there_with_the_amount(
        self, funded_developer, client: AsyncClient
    ) -> None:
        _dev_id, key, addr, fc = funded_developer
        await _deposit(fc, addr, 50)

        rows = (await client.get("/billing/ledger", headers=auth(key))).json()
        credit = next(
            r for r in rows if r["reason"] == "chain_deposit" and r["direction"] == "credit"
        )
        assert Decimal(str(credit["amount"])) == Decimal("50")
        assert credit["tx_hash"].startswith("0x")

    async def test_both_legs_come_back_so_the_group_still_balances(
        self, funded_developer, client: AsyncClient
    ) -> None:
        """The UI groups by entry_group to show each transaction nets to zero; returning
        only the developer's leg would make every deposit look unbalanced."""
        _dev_id, key, addr, fc = funded_developer
        await _deposit(fc, addr, 50)

        rows = [
            r
            for r in (await client.get("/billing/ledger", headers=auth(key))).json()
            if r["reason"] == "chain_deposit"
        ]
        assert len(rows) == 2
        assert len({r["entry_group"] for r in rows}) == 1
        debits = sum(Decimal(str(r["amount"])) for r in rows if r["direction"] == "debit")
        credits = sum(Decimal(str(r["amount"])) for r in rows if r["direction"] == "credit")
        assert debits == credits

    async def test_one_developer_cannot_see_anothers_top_ups(
        self, funded_developer, client: AsyncClient
    ) -> None:
        _dev_id, _key, addr, fc = funded_developer
        await _deposit(fc, addr, 50)

        other_id, other_key = await register(client, "developer", "Rival")
        await _link_wallet(other_id, wallet("b"))

        rows = (await client.get("/billing/ledger", headers=auth(other_key))).json()
        assert [r for r in rows if r["reason"] == "chain_deposit"] == []
