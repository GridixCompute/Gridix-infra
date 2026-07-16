#!/usr/bin/env python3
"""Drive the FULL SettlementEngine (not the raw client) against live Sepolia.

Gap #1 proved the raw Web3ChainClient send-path live. This goes one level up: it runs the real
`app.chain.settlement.SettlementEngine` — durable nonce reservation, ChainSettlement/
ProviderSettlement rows, the record→broadcast→recover→confirm state machine, and idempotency —
against live Sepolia, over a real (SQLite) database. The engine's logic is otherwise only proven
against the in-memory FakeChain; this shows the SAME code orchestrating real transactions.

Preconditions already on-chain from the Gap-#1 run (no setup tx needed): our key holds
COORDINATOR_ROLE on the exercise pair, escrow.balanceOf(us) >= 3 USDC (funds the debit), and the
settlement pool >= 2 USDC (funds the payout) — so the engine emits exactly two txs:

    settle_batch(provider, 2 USDC)   @ reserved nonce N
    debit(developer, 3 USDC)         @ reserved nonce N+1

Then a second forced tick must find nothing new (idempotency) — no third tx, no double-pay.

Run:  cd /home/eonedge/Gridix && .venv/bin/python smoke/drive_settlement_engine_sepolia.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

_DB = Path(tempfile.gettempdir()) / "gridix_settlement_sepolia.sqlite3"
os.environ["GRIDIX_DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB}"
os.environ.setdefault("GRIDIX_ENV", "dev")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from app.chain.client import Web3ChainClient  # noqa: E402
from app.chain.settlement import SettlementEngine  # noqa: E402
from app.chain.signer import LocalKeySigner  # noqa: E402
from app.db import Base, get_engine, get_sessionmaker  # noqa: E402
from app.ledger import Posting, post_transaction  # noqa: E402
from app.models import (  # noqa: E402
    ChainSettlement,
    ChainTxKind,
    ChainTxStatus,
    Developer,
    LedgerAccount,
    LedgerDirection,
    Provider,
)
from sqlalchemy import select  # noqa: E402

CHAIN_ID = 11155111
ESCROW = "0x04B237e8b5F3de59F02C3E61007351Eb5d8CA09B"
STAKING = "0xfc51f5439c96B47B37304BBd63147ef53d15D01F"
PROVIDER_WALLET = "0x000000000000000000000000000000000000dEaD"  # settleBatch payout target (mock)
CONF = 2  # confirmations the engine waits before marking a row confirmed

EARN = Decimal("2")  # provider off-chain earnings -> settle_batch payout (USDC)
CONSUMED = Decimal("3")  # developer escrow consumed off-chain -> on-chain debit (USDC)


def _load_env() -> tuple[str, str]:
    env = {}
    for line in (
        (Path(__file__).resolve().parent.parent / "contracts" / ".env").read_text().splitlines()
    ):
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env["SEPOLIA_RPC_URL"], env["PRIVATE_KEY"]


async def _reset_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def _seed(dev_wallet: str) -> tuple[str, str]:
    """Seed one provider (earned off-chain) + one developer (consumed off-chain)."""
    async with get_sessionmaker()() as s:
        dev = Developer(name="live-dev", wallet_address=dev_wallet)
        prov = Provider(name="live-prov", wallet_address=PROVIDER_WALLET)
        s.add_all([dev, prov])
        await s.flush()
        did, pid = dev.id, prov.id
        # provider earned (a settle posting would look like this): protocol -> provider
        await post_transaction(
            s,
            [
                Posting(LedgerAccount.protocol, LedgerDirection.debit, EARN),
                Posting(LedgerAccount.provider, LedgerDirection.credit, EARN, pid),
            ],
            reason="settle",
        )
        # developer consumed escrow (drives the on-chain debit): escrow -> protocol
        await post_transaction(
            s,
            [
                Posting(LedgerAccount.escrow, LedgerDirection.debit, CONSUMED, did),
                Posting(LedgerAccount.protocol, LedgerDirection.credit, CONSUMED),
            ],
            reason="settle",
        )
        await s.commit()
        return str(did), str(pid)


async def _rows() -> list[ChainSettlement]:
    async with get_sessionmaker()() as s:
        return list(await s.scalars(select(ChainSettlement).order_by(ChainSettlement.nonce)))


async def main() -> None:
    rpc, key = _load_env()
    client = Web3ChainClient(
        rpc_url=rpc,
        chain_id=CHAIN_ID,
        escrow_address=ESCROW,
        staking_address=STAKING,
        signer=LocalKeySigner(key),
    )
    dev_wallet = client.coordinator_address  # our key doubles as the developer (holds escrow)
    print(f"RPC={rpc}\ncoordinator/developer={dev_wallet}\nDB={_DB}\n")

    await _reset_db()
    did, pid = await _seed(dev_wallet)
    print(f"seeded developer={did} provider={pid} (earn={EARN} consumed={CONSUMED} USDC)\n")

    engine = SettlementEngine(
        client,
        get_sessionmaker(),
        usdc_decimals=6,
        confirmations=CONF,
        threshold_usdc=Decimal("1000"),  # high; we force the cycle
        interval_seconds=3600.0,
    )

    # baseline on-chain state
    earn0 = await client.staking_earnings_of(PROVIDER_WALLET)
    esc0 = await client.escrow_balance_of(dev_wallet)
    pool0 = await client.settlement_pool()
    print(f"before: earnings(prov)={earn0} escrow(dev)={esc0} pool={pool0}")

    # ── drive forced ticks until fully settled ─────────────────────────────────────────
    # The engine serialises deliberately: _maybe_debit skips while anything is in-flight, so a
    # settle_batch confirms FIRST, then a later tick records + broadcasts the debit. We drive
    # forced ticks (each recovers in-flight rows, then records any new intent) until a forced
    # tick finds nothing new AND no rows are still live — i.e. settle + debit both confirmed.
    print("[driving] forced ticks: settle_batch -> confirm -> debit -> confirm ...")
    for i in range(45):  # ~45 * 8s ceiling
        r = await engine.tick(force=True)
        rows = await _rows()
        states = {row.kind.value: row.status.value for row in rows}
        live = [row for row in rows if row.status.value in ("pending", "submitted")]
        print(
            f"    round {i}: {states}  (batched={r.batched} debited={r.debited} "
            f"confirmed={r.confirmed} failed={r.failed})"
        )
        if rows and not live and r.batched == 0 and r.debited == 0:
            break
        await asyncio.sleep(8)
    else:
        raise SystemExit("!! did not reach a fully-settled steady state within timeout")

    rows = await _rows()
    assert all(row.status is ChainTxStatus.confirmed for row in rows), "not all confirmed"
    settle = next(row for row in rows if row.kind is ChainTxKind.settle_batch)
    debit = next(row for row in rows if row.kind is ChainTxKind.debit)
    assert debit.nonce == settle.nonce + 1, "debit must be reserved at settle_nonce + 1"
    print(f"\n  settle_batch: nonce={settle.nonce} block={settle.block_number} tx={settle.tx_hash}")
    print(f"  debit       : nonce={debit.nonce} block={debit.block_number} tx={debit.tx_hash}")

    # ── on-chain effects moved exactly as the engine intended ──────────────────────────
    earn1 = await client.staking_earnings_of(PROVIDER_WALLET)
    esc1 = await client.escrow_balance_of(dev_wallet)
    print(
        f"\nafter : earnings(prov)={earn1} (+{earn1 - earn0})  escrow(dev)={esc1} ({esc1 - esc0})"
    )
    assert earn1 - earn0 == 2_000_000, "settle_batch payout wrong"
    assert esc0 - esc1 == 3_000_000, "debit amount wrong"
    print("  OK settle_batch paid +2 USDC, debit pulled -3 USDC  ✓")

    # ── idempotency: a second forced tick must NOT create a new batch/debit ─────────────
    r2 = await engine.tick(force=True)
    rows_after = await _rows()
    print(
        f"\n[tick 2 — idempotency] batched={r2.batched} debited={r2.debited} rows={len(rows_after)}"
    )
    assert r2.batched == 0 and r2.debited == 0, "engine re-settled already-settled earnings!"
    assert len(rows_after) == len(rows), "engine created duplicate settlement rows!"
    print("  OK second forced tick found nothing new — no double-pay  ✓")

    print("\nFULL ENGINE PROVEN AGAINST LIVE SEPOLIA ✓")


if __name__ == "__main__":
    asyncio.run(main())
