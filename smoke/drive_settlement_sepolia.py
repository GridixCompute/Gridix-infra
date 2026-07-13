#!/usr/bin/env python3
"""Drive the backend's REAL Web3ChainClient write-path against live Sepolia (Gap #1).

The Session-13 settlement engine is proven against FakeChain; what was never exercised live
is the Python send-path itself — signing, live-chain nonce, gas estimation, ABI encoding, and
receipt polling in `app.chain.client.Web3ChainClient`. This script closes that gap.

It reuses the throwaway MockUSDC exercise pair already on Sepolia (contracts/EVIDENCE.md), where
our deployer key holds COORDINATOR_ROLE on both contracts — so no new deploy, minimal gas. The
three COORDINATOR write methods are called through the backend client verbatim:

    escrow.debit            <- client.send_debit
    staking.depositSettlement <- client.send_deposit_settlement
    staking.settleBatch     <- client.send_settle_batch

Setup steps (approve / deposit — developer-side, not part of the proof) use web3 directly.
Everything runs from the single deployer key acting as developer + coordinator. Amounts are
tiny (MockUSDC, 6-dec). Prints tx hashes + before/after on-chain state for the evidence file.

Run:  cd /home/eonedge/Gridix && .venv/bin/python smoke/drive_settlement_sepolia.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from eth_account import Account
from web3 import AsyncHTTPProvider, AsyncWeb3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
from app.chain.client import Web3ChainClient  # noqa: E402

# ── live Sepolia exercise pair (throwaway MockUSDC; our key = coordinator) ──────────────
CHAIN_ID = 11155111
ESCROW = "0x04B237e8b5F3de59F02C3E61007351Eb5d8CA09B"
STAKING = "0xfc51f5439c96B47B37304BBd63147ef53d15D01F"
USDC = "0x48d9eb22261094f9C2F31587daD06fa80df6d23B"
PROVIDER = "0x000000000000000000000000000000000000dEaD"  # payout target for settleBatch (mock)

# amounts in raw USDC units (6 decimals)
DEPOSIT = 10_000_000  # 10 USDC developer deposit (funds escrow so debit has balance)
DEBIT = 3_000_000  # 3 USDC coordinator debit -> treasury
POOL = 5_000_000  # 5 USDC coordinator depositSettlement -> settlement pool
SETTLE = 2_000_000  # 2 USDC settleBatch payout to PROVIDER (<= pool)

_ERC20 = [
    {
        "type": "function",
        "name": "approve",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "o", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]
_ESCROW_DEPOSIT = [
    {
        "type": "function",
        "name": "deposit",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "amount", "type": "uint256"}],
        "outputs": [],
    }
]


def _load_env() -> tuple[str, str]:
    env = {}
    for line in (
        (Path(__file__).resolve().parent.parent / "contracts" / ".env").read_text().splitlines()
    ):
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    rpc = os.environ.get("SEPOLIA_RPC_URL") or env["SEPOLIA_RPC_URL"]
    key = os.environ.get("PRIVATE_KEY") or env["PRIVATE_KEY"]
    return rpc, key


async def _send_raw(w3: AsyncWeb3, acct, fn) -> str:
    """Build/sign/broadcast a tx from `acct` — mirrors Web3ChainClient._send for setup steps."""
    nonce = await w3.eth.get_transaction_count(acct.address, "pending")
    gas = await fn.estimate_gas({"from": acct.address})
    tx = await fn.build_transaction(
        {
            "from": acct.address,
            "nonce": nonce,
            "chainId": CHAIN_ID,
            "gas": int(gas * 1.25),
            "maxFeePerGas": await w3.eth.gas_price,
            "maxPriorityFeePerGas": w3.to_wei(1, "gwei"),
        }
    )
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = await w3.eth.send_raw_transaction(raw)
    return h.hex() if hasattr(h, "hex") else str(h)


async def _wait(client: Web3ChainClient, tx_hash: str, label: str) -> None:
    for _ in range(75):  # ~300s ceiling; a slightly under-priced tx can take extra blocks
        r = await client.get_receipt(tx_hash)
        if r is not None:
            status = "SUCCESS" if r.status == 1 else "REVERTED"
            print(f"    {label}: {tx_hash}  status={r.status} ({status}) block={r.block_number}")
            if r.status != 1:
                raise SystemExit(f"!! {label} reverted on-chain")
            return
        await asyncio.sleep(4)
    raise SystemExit(f"!! {label} not mined within timeout ({tx_hash})")


async def main() -> None:
    rpc, key = _load_env()
    acct = Account.from_key(key)
    dev = acct.address  # our key plays developer + coordinator
    print(f"RPC={rpc}\nsigner (dev+coordinator)={dev}\n")

    w3 = AsyncWeb3(AsyncHTTPProvider(rpc))
    usdc = w3.eth.contract(address=w3.to_checksum_address(USDC), abi=_ERC20)
    escrow_dep = w3.eth.contract(address=w3.to_checksum_address(ESCROW), abi=_ESCROW_DEPOSIT)

    # the actual subject under test: the backend's real chain client
    client = Web3ChainClient(
        rpc_url=rpc,
        chain_id=CHAIN_ID,
        escrow_address=ESCROW,
        staking_address=STAKING,
        coordinator_private_key=key,
    )

    escrow_cs = w3.to_checksum_address(ESCROW)
    staking_cs = w3.to_checksum_address(STAKING)

    async def state(tag: str) -> None:
        eb = await client.escrow_balance_of(dev)
        pool = await client.settlement_pool()
        earn = await client.staking_earnings_of(PROVIDER)
        ub = int(await usdc.functions.balanceOf(dev).call())
        print(f"  [{tag}] escrow.balanceOf(dev)={eb} pool={pool} earnings(p)={earn} usdc(dev)={ub}")

    async def setup(fn, label: str) -> None:
        """Developer/coordinator setup tx via web3 (not part of the proof)."""
        await _wait(client, await _send_raw(w3, acct, fn), label)

    async def prove(coro, label: str) -> None:
        """A backend-client write call (the actual subject under test)."""
        await _wait(client, await coro, label)

    bal_wei = int(await w3.eth.get_balance(dev))
    gwei = (await w3.eth.gas_price) / 1e9
    print(f"gas balance: {bal_wei / 1e18:.6f} ETH  (gas price {gwei:.2f} gwei)\n")
    await state("before")

    # ── setup (not the proof): fund escrow so debit has a balance to pull ──────────────
    print("\n[setup] approve escrow + deposit (developer side, via web3)")
    await setup(usdc.functions.approve(escrow_cs, DEPOSIT), "approve->escrow")
    await setup(escrow_dep.functions.deposit(DEPOSIT), "deposit")
    await state("after deposit")

    # ── PROOF 1: escrow.debit via backend client ───────────────────────────────────────
    print("\n[PROOF 1] client.send_debit  (COORDINATOR_ROLE)")
    eb0 = await client.escrow_balance_of(dev)
    await prove(client.send_debit(dev, DEBIT, await client.get_nonce(pending=True)), "send_debit")
    eb1 = await client.escrow_balance_of(dev)
    assert eb1 == eb0 - DEBIT, f"debit accounting off: {eb0} -> {eb1}, expected -{DEBIT}"
    print(f"    OK escrow.balanceOf(dev) {eb0} -> {eb1} (-{DEBIT}) OK")

    # ── setup: approve staking so depositSettlement can pull the pool funding ───────────
    print("\n[setup] approve staking (coordinator side, via web3)")
    await setup(usdc.functions.approve(staking_cs, POOL), "approve->staking")

    # ── PROOF 2: staking.depositSettlement via backend client ──────────────────────────
    print("\n[PROOF 2] client.send_deposit_settlement")
    p0 = await client.settlement_pool()
    nonce = await client.get_nonce(pending=True)
    await prove(client.send_deposit_settlement(POOL, nonce), "send_deposit_settlement")
    p1 = await client.settlement_pool()
    assert p1 == p0 + POOL, f"pool accounting off: {p0} -> {p1}, expected +{POOL}"
    print(f"    OK settlementPool {p0} -> {p1} (+{POOL}) OK")

    # ── PROOF 3: staking.settleBatch via backend client ────────────────────────────────
    print("\n[PROOF 3] client.send_settle_batch  (batch payout)")
    e0 = await client.staking_earnings_of(PROVIDER)
    p1 = await client.settlement_pool()
    nonce = await client.get_nonce(pending=True)
    await prove(client.send_settle_batch([PROVIDER], [SETTLE], nonce), "send_settle_batch")
    e1 = await client.staking_earnings_of(PROVIDER)
    p2 = await client.settlement_pool()
    assert e1 == e0 + SETTLE and p2 == p1 - SETTLE, f"settle off: earn {e0}->{e1}, pool {p1}->{p2}"
    print(f"    OK earnings(p) {e0} -> {e1} (+{SETTLE}), pool {p1} -> {p2} (-{SETTLE}) OK")

    await state("after")
    bal_end = int(await w3.eth.get_balance(dev))
    print(f"\ngas spent: {(bal_wei - bal_end) / 1e18:.6f} ETH")
    print("\nALL 3 WRITE-PATH PROOFS PASSED on live Sepolia")


if __name__ == "__main__":
    asyncio.run(main())
