"""Session 13 — on-chain settlement layer, driven entirely by the in-memory FakeChain.

Proves the DoD invariants without touching a network:
  * submit gate rejects a job a developer can't cover (403);
  * settlement is idempotent — a crash mid-settle never double-pays;
  * a reverted settleBatch releases its reservation and retries;
  * the watcher applies effects only after N confirmations and rolls back on reorg;
  * reconciliation is zero on a clean flow and flags real divergence (→ gauge → alert);
  * the off-chain ledger stays balanced throughout (old invariant survives).
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.alerts import evaluate_alerts
from app.chain.bootstrap import install_chain_client
from app.chain.fake import FakeChain
from app.chain.reconcile import CHAIN_DIVERGENCE, Reconciler
from app.chain.registry import set_chain_client
from app.chain.settlement import SettlementEngine
from app.chain.watcher import ChainWatcher
from app.config import get_settings
from app.db import get_sessionmaker
from app.ledger import Posting, account_balance, post_transaction, verify_ledger_integrity
from app.models import (
    ChainSettlement,
    ChainTxKind,
    ChainTxStatus,
    Developer,
    LedgerAccount,
    LedgerDirection,
    Provider,
)
from app.payments import FiatStub, get_payment_provider, set_payment_provider
from conftest import auth, register
from sqlalchemy import select

CONF = 2  # confirmations depth used across these tests (keeps mining cheap)
USDC = 1_000_000


def wallet(tag: str) -> str:
    return "0x" + (tag * 40)[:40]


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


@pytest.fixture
def restore_provider():
    """Save/restore the process-global payment provider + chain client around a test."""
    saved = get_payment_provider()
    yield
    set_payment_provider(saved)
    set_chain_client(None)


def _engine(fc: FakeChain, **kw) -> SettlementEngine:
    return SettlementEngine(
        fc,
        get_sessionmaker(),
        usdc_decimals=6,
        confirmations=CONF,
        threshold_usdc=kw.get("threshold", Decimal("1000")),
        interval_seconds=kw.get("interval", 3600.0),
    )


def _watcher(fc: FakeChain) -> ChainWatcher:
    return ChainWatcher(fc, get_sessionmaker(), usdc_decimals=6, confirmations=CONF)


async def _drive(fc: FakeChain, engine: SettlementEngine, watcher: ChainWatcher, rounds=12):
    """Push the chain forward: force settlement, mine, ingest events — until it settles down."""
    for _ in range(rounds):
        await engine.tick(force=True)
        fc.mine(1)
        await watcher.tick()


async def _earn(provider_id: uuid.UUID, amount: Decimal, *, reason="settle"):
    """Credit a provider's off-chain earnings (as a settle posting would)."""
    async with get_sessionmaker()() as s:
        await post_transaction(
            s,
            [
                Posting(LedgerAccount.protocol, LedgerDirection.debit, amount),
                Posting(LedgerAccount.provider, LedgerDirection.credit, amount, provider_id),
            ],
            reason=reason,
        )
        await s.commit()


# ── submit gate ─────────────────────────────────────────────────────────────────────────
async def test_submit_gate_rejects_when_unfunded_then_allows_after_deposit(
    client, restore_provider, _no_redis
):
    dev_id, dev_key = await register(client, "developer", "Acme")
    w = wallet("a")
    async with get_sessionmaker()() as s:
        dev = await s.get(Developer, uuid.UUID(dev_id))
        dev.wallet_address = w
        await s.commit()

    fc = FakeChain()
    install_chain_client(get_settings(), fc)  # installs USDCPaymentProvider over the fake

    # No deposit yet → available 0 → 403.
    r = await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "img"})
    assert r.status_code == 403, r.text
    assert "Insufficient balance" in r.json()["error"]["message"]

    # Deposit on-chain, confirm, let the watcher credit the ledger → now affordable → 201.
    fc.external_deposit(w, 50 * USDC)
    fc.mine(CONF)
    await _watcher(fc).tick()
    get_payment_provider().invalidate(w)  # drop the cached 0-balance
    r = await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "img"})
    assert r.status_code == 201, r.text


async def test_fiat_mode_has_no_gate(client, restore_provider, _no_redis):
    """With no chain client (FiatStub), submit is never gated on balance."""
    set_payment_provider(FiatStub())
    _dev, dev_key = await register(client, "developer", "Acme")
    r = await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "img"})
    assert r.status_code == 201, r.text


# ── settlement idempotency ────────────────────────────────────────────────────────────────
async def test_settlement_no_double_pay_across_crash(restore_provider):
    async with get_sessionmaker()() as s:
        p = Provider(name="p", wallet_address=wallet("b"))
        s.add(p)
        await s.flush()
        pid, pw = p.id, p.wallet_address
        await s.commit()
    await _earn(pid, Decimal("40"))

    fc = FakeChain()
    # Engine A builds + broadcasts the batch, then we "crash" (discard it) before confirming.
    engine_a = _engine(fc)
    r = await engine_a.tick(force=True)
    assert r.batched == 1

    # Fresh engine instance (simulated restart), same DB + chain. It must NOT rebuild the batch.
    engine_b = _engine(fc)
    fc.mine(CONF + 1)
    await engine_b.tick()  # recovery confirms the existing tx
    await engine_b.tick(force=True)  # a forced cycle must find nothing new to settle

    assert await fc.staking_earnings_of(pw) == 40 * USDC  # paid exactly once
    async with get_sessionmaker()() as s:
        rows = list(
            await s.scalars(
                select(ChainSettlement).where(ChainSettlement.kind == ChainTxKind.settle_batch)
            )
        )
        assert len(rows) == 1 and rows[0].status is ChainTxStatus.confirmed


async def test_settlement_recovers_when_broadcast_crashed_before_send(restore_provider):
    """Crash between recording the batch and broadcasting: recovery re-sends at the same nonce."""
    async with get_sessionmaker()() as s:
        p = Provider(name="p", wallet_address=wallet("c"))
        s.add(p)
        await s.flush()
        pid, pw = p.id, p.wallet_address
        await s.commit()
    await _earn(pid, Decimal("25"))

    fc = FakeChain()
    fc.fail_next_send(True)  # the settleBatch broadcast throws after rows are committed
    engine = _engine(fc)
    await engine.tick(force=True)  # rows written (pending), broadcast failed
    async with get_sessionmaker()() as s:
        pending = list(
            await s.scalars(
                select(ChainSettlement).where(ChainSettlement.status == ChainTxStatus.pending)
            )
        )
        assert pending  # durable intent survived the failed send

    # Recovery re-broadcasts and confirms — exactly one payout.
    for _ in range(CONF + 3):
        await engine.tick()
        fc.mine(1)
    assert await fc.staking_earnings_of(pw) == 25 * USDC


async def test_reverted_settlement_releases_reservation_and_retries(restore_provider):
    async with get_sessionmaker()() as s:
        p = Provider(name="p", wallet_address=wallet("d"))
        s.add(p)
        await s.flush()
        pid, pw = p.id, p.wallet_address
        await s.commit()
    await _earn(pid, Decimal("30"))

    fc = FakeChain()
    fc.force_revert("settle_batch", True)
    engine = _engine(fc)
    await engine.tick(force=True)
    fc.mine(CONF + 1)
    await engine.tick()  # recovery sees the revert → marks failed, releases reservation
    async with get_sessionmaker()() as s:
        failed = list(
            await s.scalars(
                select(ChainSettlement).where(ChainSettlement.status == ChainTxStatus.failed)
            )
        )
        assert failed

    # Stop reverting → the released earnings settle on the next cycle.
    fc.force_revert("settle_batch", False)
    await _drive(fc, engine, _watcher(fc))
    assert await fc.staking_earnings_of(pw) == 30 * USDC


# ── watcher confirmations + reorg ──────────────────────────────────────────────────────────
async def test_watcher_waits_for_confirmations_and_reverses_reorg(restore_provider):
    w = wallet("e")
    async with get_sessionmaker()() as s:
        d = Developer(name="d", wallet_address=w)
        s.add(d)
        await s.flush()
        did = d.id
        await s.commit()
    fc = FakeChain()
    watcher = _watcher(fc)

    async def dev_balance():
        async with get_sessionmaker()() as s:
            return await account_balance(s, LedgerAccount.developer, did)

    fc.external_deposit(w, 100 * USDC)
    fc.mine(1)
    await watcher.tick()
    assert await dev_balance() == 0  # 1 block deep < CONF → not applied

    fc.mine(CONF)
    await watcher.tick()
    assert await dev_balance() == 100  # now final → credited

    # Confirm a second deposit, then reorg deeper than CONF → the applied effect must reverse.
    fc.external_deposit(w, 20 * USDC)
    fc.mine(CONF)
    await watcher.tick()
    assert await dev_balance() == 120
    fc.reorg(depth=CONF + 2, remine=CONF + 2)
    await watcher.tick()
    assert await dev_balance() == 100  # orphaned deposit rolled back


# ── reconciliation ─────────────────────────────────────────────────────────────────────────
async def _full_clean_flow():
    """Deposit → hold → settle → on-chain settle+debit, all confirmed. Returns (fc, dev, prov)."""
    async with get_sessionmaker()() as s:
        d = Developer(name="d", wallet_address=wallet("1"))
        p = Provider(name="p", wallet_address=wallet("2"))
        s.add_all([d, p])
        await s.flush()
        did, dw, pid, pw = d.id, d.wallet_address, p.id, p.wallet_address
        await s.commit()

    fc = FakeChain()
    install_chain_client(get_settings(), fc)
    provider = get_payment_provider()
    watcher = _watcher(fc)
    engine = _engine(fc)

    # 1) developer deposits 100 on-chain → watcher credits ledger.
    fc.external_deposit(dw, 100 * USDC)
    fc.mine(CONF)
    await watcher.tick()

    # 2) a job runs: hold 10, settle 10 (9 to provider, 1 protocol fee) — off-chain.
    job = uuid.uuid4()
    async with get_sessionmaker()() as s:
        await provider.hold_escrow(s, job, did, Decimal("10"))
        await provider.settle(s, job, did, pid, Decimal("10"), Decimal("1"))
        await s.commit()

    # 3) aggregate settle (provider) + debit (developer) on-chain, confirmed.
    await _drive(fc, engine, watcher, rounds=16)
    return fc, did, dw, pid, pw


async def test_reconciliation_zero_on_clean_flow(restore_provider):
    fc, did, dw, pid, pw = await _full_clean_flow()
    # provider paid 9, developer escrow debited 10.
    assert await fc.staking_earnings_of(pw) == 9 * USDC
    assert await fc.escrow_balance_of(dw) == 90 * USDC

    reconciler = Reconciler(fc, get_sessionmaker(), usdc_decimals=6)
    divergences = await reconciler.run()
    assert divergences == [], divergences
    assert CHAIN_DIVERGENCE._value.get() == 0

    async with get_sessionmaker()() as s:
        assert await verify_ledger_integrity(s) == []  # old money invariant still holds


async def test_reconciliation_detects_divergence_and_alerts(restore_provider):
    fc, did, dw, pid, pw = await _full_clean_flow()
    reconciler = Reconciler(fc, get_sessionmaker(), usdc_decimals=6)
    assert await reconciler.run() == []

    # Someone settles 5 USDC on-chain to the provider outside our records → observed > recorded.
    fc.fund_pool(5 * USDC)
    rogue_nonce = await fc.get_nonce()
    await fc.send_settle_batch([pw], [5 * USDC], nonce=rogue_nonce)
    fc.mine(CONF)
    await _watcher(fc).tick()

    divergences = await reconciler.run()
    assert len(divergences) >= 1
    assert any(d.kind == "provider_settled" for d in divergences)
    assert CHAIN_DIVERGENCE._value.get() == len(divergences)

    # The divergence count feeds the same alert path proven in 12.7.
    alerts = evaluate_alerts({"chain_divergences": len(divergences)}, get_settings())
    assert any(a.name == "chain_ledger_divergence" and a.severity == "critical" for a in alerts)


async def test_no_job_lost_and_ledger_balanced_after_settlement(restore_provider):
    """The two legacy invariants survive: every ledger group balances, nothing is stranded."""
    fc, did, dw, pid, pw = await _full_clean_flow()
    async with get_sessionmaker()() as s:
        assert await verify_ledger_integrity(s) == []
        # provider earned exactly what was settled on-chain (no earnings lost or invented).
        earned = await account_balance(s, LedgerAccount.provider, pid)
    assert earned == Decimal("9")
    assert await fc.staking_earnings_of(pw) == 9 * USDC
