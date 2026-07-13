#!/usr/bin/env python3
"""Close the last seam: the coordinator key SOURCED FROM VAULT actually signs live txs.

Prior proofs covered each piece separately — Vault→key read, key→client build + address assert,
and coordinator→debit/settleBatch broadcast (signed by the .env key). This composes them: the
key is fetched from Vault via the real startup path (init_secrets + install_chain), and THAT
client broadcasts a real debit + settleBatch on the exercise pair (MockUSDC we control).

Setup (developer deposit) is signed by the .env admin/dev key; the debit + settleBatch are signed
by the Vault-sourced coordinator (0xBbBe…). Everything is on the throwaway MockUSDC exercise pair.

Config from env: GRIDIX_SECRET_BACKEND=vault + vault creds + chain_* pointing at the exercise pair
+ GRIDIX_EXPECTED_COORDINATOR_ADDRESS. The coordinator key is never printed.

Run: see the invocation in the session (needs a live Vault provisioned with the coordinator key).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from eth_account import Account
from web3 import AsyncHTTPProvider, AsyncWeb3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

from app.chain.bootstrap import install_chain  # noqa: E402
from app.config import Settings  # noqa: E402
from app.secret_manager import init_secrets  # noqa: E402

USDC = "0x48d9eb22261094f9C2F31587daD06fa80df6d23B"  # MockUSDC (mintable, ours)
DEPOSIT = 5_000_000  # dev deposits 5 MockUSDC into escrow (funds the debit)
DEBIT = 2_000_000  # coordinator debits 2 (signed by the Vault key)
SETTLE = 1_000_000  # coordinator settles 1 to a provider off the existing pool
PROVIDER = "0x000000000000000000000000000000000000dEaD"

_ERC20 = [
    {
        "type": "function",
        "name": "approve",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
]
_DEPOSIT_ABI = [
    {
        "type": "function",
        "name": "deposit",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "amount", "type": "uint256"}],
        "outputs": [],
    },
]


def _dev_key() -> str:
    for line in (
        (Path(__file__).resolve().parents[2] / "contracts" / ".env").read_text().splitlines()
    ):
        if line.startswith("PRIVATE_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("PRIVATE_KEY not found")


async def _send_raw(w3: AsyncWeb3, acct, fn) -> str:
    nonce = await w3.eth.get_transaction_count(acct.address, "pending")
    gas = await fn.estimate_gas({"from": acct.address})
    gas_price = await w3.eth.gas_price
    tip = min(w3.to_wei(1, "gwei"), gas_price)  # tip must not exceed maxFee on a quiet chain
    tx = await fn.build_transaction(
        {
            "from": acct.address,
            "nonce": nonce,
            "chainId": 11155111,
            "gas": int(gas * 1.3),
            "maxFeePerGas": gas_price + tip,
            "maxPriorityFeePerGas": tip,
        }
    )
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    return (await w3.eth.send_raw_transaction(raw)).hex()


async def _wait(client, tx: str, label: str) -> None:
    if not tx.startswith("0x"):
        tx = "0x" + tx
    for _ in range(75):
        r = await client.get_receipt(tx)
        if r is not None:
            print(f"    {label}: {tx} status={r.status} block={r.block_number}")
            if r.status != 1:
                raise SystemExit(f"{label} reverted")
            return
        await asyncio.sleep(4)
    raise SystemExit(f"{label} not mined")


async def main() -> None:
    settings = Settings()
    assert settings.secret_backend == "vault" and settings.chain_enabled
    init_secrets(settings)  # Vault manager installed
    client = install_chain(
        settings
    )  # coordinator client built from the Vault key + address-asserted
    assert client is not None
    coord = client.coordinator_address
    print(f"coordinator (from Vault) = {coord}")
    assert coord == settings.expected_coordinator_address.lower()

    rpc = settings.chain_rpc_url
    dev = Account.from_key(_dev_key())
    w3 = AsyncWeb3(AsyncHTTPProvider(rpc))
    usdc = w3.eth.contract(address=w3.to_checksum_address(USDC), abi=_ERC20)
    escrow = w3.eth.contract(
        address=w3.to_checksum_address(settings.escrow_address), abi=_DEPOSIT_ABI
    )

    print(f"\n[setup] dev {dev.address} approves + deposits {DEPOSIT} MockUSDC (dev-signed)")
    await _wait(
        client,
        await _send_raw(
            w3,
            dev,
            usdc.functions.approve(w3.to_checksum_address(settings.escrow_address), DEPOSIT),
        ),
        "approve",
    )
    await _wait(client, await _send_raw(w3, dev, escrow.functions.deposit(DEPOSIT)), "deposit")

    eb0 = await client.escrow_balance_of(dev.address)
    pool0 = await client.settlement_pool()
    earn0 = await client.staking_earnings_of(PROVIDER)
    print(f"before: escrow(dev)={eb0} pool={pool0} earnings(p)={earn0}")
    if pool0 < SETTLE:
        raise SystemExit(f"pool {pool0} < settle {SETTLE} — fund the pool first")

    print("\n[PROOF] debit signed by the VAULT-sourced coordinator key")
    await _wait(
        client, await client.send_debit(dev.address, DEBIT, await client.get_nonce()), "send_debit"
    )
    eb1 = await client.escrow_balance_of(dev.address)
    assert eb1 == eb0 - DEBIT, f"debit off: {eb0}->{eb1}"
    print(f"    OK escrow(dev) {eb0} -> {eb1} (-{DEBIT})")

    print("\n[PROOF] settleBatch signed by the VAULT-sourced coordinator key")
    await _wait(
        client,
        await client.send_settle_batch([PROVIDER], [SETTLE], await client.get_nonce()),
        "send_settle_batch",
    )
    earn1 = await client.staking_earnings_of(PROVIDER)
    assert earn1 == earn0 + SETTLE, f"settle off: {earn0}->{earn1}"
    print(f"    OK earnings(p) {earn0} -> {earn1} (+{SETTLE})")

    print("\nVAULT-SOURCED COORDINATOR KEY SIGNED LIVE debit + settleBatch ✓ (seam closed)")


if __name__ == "__main__":
    asyncio.run(main())
