#!/usr/bin/env python3
"""Read-only proof: run the watcher + reconciler against the PRODUCTION contracts.

This touches NO funds and sends NO transaction — the watcher only reads logs/blocks and writes to
the local (SQLite) off-chain ledger; the reconciler only reads on-chain balances and compares. It
proves the backend can observe and reconcile the real production deployment
(0xd930…/0x7208…), not just the throwaway exercise pair.

The Web3ChainClient constructor needs a key to derive its signer, but NONE of the calls here sign
anything — we pass the admin key purely to construct the client; it is never used to send a tx.

Run:  cd /home/eonedge/Gridix && .venv/bin/python smoke/reconcile_prod_readonly.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

_DB = Path(tempfile.gettempdir()) / "gridix_reconcile_prod.sqlite3"
os.environ["GRIDIX_DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB}"
os.environ.setdefault("GRIDIX_ENV", "dev")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from app.chain.client import Web3ChainClient  # noqa: E402
from app.chain.reconcile import CHAIN_DIVERGENCE, Reconciler  # noqa: E402
from app.chain.watcher import ChainWatcher  # noqa: E402
from app.db import Base, get_engine, get_sessionmaker  # noqa: E402

# PRODUCTION deployment (contracts/EVIDENCE.md) — the real thing, not the exercise pair.
CHAIN_ID = 11155111
ESCROW = "0xd93076eb67ab21ae068c0ad7a6256ca6ba58f733"
STAKING = "0x72089171441d05ad2a64777177fF2864a9703822"
ESCROW_DEPLOY_BLOCK = 11262619  # fresh watcher cursor starts here, not genesis
CONF = 3


def _load_env() -> tuple[str, str]:
    env = {}
    src = Path(__file__).resolve().parent.parent / "contracts" / ".env"
    for line in src.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    # publicnode gates eth_getLogs on old ranges behind a paid "archive" token; a catch-up scan
    # from the deploy block needs an archive-capable endpoint. Override with GRIDIX_CHAIN_RPC_URL.
    rpc = os.environ.get("GRIDIX_CHAIN_RPC_URL") or env["SEPOLIA_RPC_URL"]
    return rpc, env["PRIVATE_KEY"]


async def _reset_db() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def _seed_wallets(client: Web3ChainClient) -> None:
    """Seed one developer + one provider with real wallets so the reconciler actually READS their
    on-chain production balances and compares — not a trivial empty-ledger pass. Both sides are 0
    on the pristine production deployment, so a correct reconcile still finds zero divergence."""
    from app.models import Developer, Provider

    async with get_sessionmaker()() as s:
        s.add(Developer(name="recon-dev", wallet_address=client.coordinator_address))
        s.add(
            Provider(name="recon-prov", wallet_address="0x000000000000000000000000000000000000dEaD")
        )
        await s.commit()


async def main() -> None:
    rpc, key = _load_env()
    client = Web3ChainClient(
        rpc_url=rpc,
        chain_id=CHAIN_ID,
        escrow_address=ESCROW,
        staking_address=STAKING,
        coordinator_private_key=key,  # constructor only; never used to sign here
        log_window=500,
    )
    print(f"RPC={rpc}\nPRODUCTION escrow={ESCROW}\nPRODUCTION staking={STAKING}\n")
    await _reset_db()

    # 1) watcher: scan production logs from the deploy block to head (read-only ingest).
    watcher = ChainWatcher(
        client,
        get_sessionmaker(),
        usdc_decimals=6,
        confirmations=CONF,
        start_block=ESCROW_DEPLOY_BLOCK,
    )
    head = await client.latest_block()
    print(f"[watcher] scanning production events {ESCROW_DEPLOY_BLOCK}..{head} (read-only)...")
    result = await watcher.tick()
    print(f"[watcher] scanned to head; applied={result}")

    # 2) reconciler: compare REAL on-chain production balances vs the off-chain ledger.
    await _seed_wallets(client)
    print("[reconcile] seeded 1 developer + 1 provider so real prod balances are read & compared")
    reconciler = Reconciler(client, get_sessionmaker(), usdc_decimals=6)
    divergences = await reconciler.run()
    print(f"\n[reconcile] divergences = {divergences}")
    print(f"[reconcile] CHAIN_DIVERGENCE gauge = {CHAIN_DIVERGENCE._value.get()}")

    assert divergences == [], f"expected zero divergence, got {divergences}"
    assert CHAIN_DIVERGENCE._value.get() == 0
    print("\nREAD-ONLY RECONCILE vs PRODUCTION: ZERO DIVERGENCE ✓ (no tx sent, no funds touched)")


if __name__ == "__main__":
    asyncio.run(main())
