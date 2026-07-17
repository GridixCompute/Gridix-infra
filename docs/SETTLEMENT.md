# On-chain settlement (Session 13)

How the GridixEscrow / GridixStaking contracts connect to the backend. **The off-chain
double-entry ledger (`app.ledger`) stays the source of truth for per-job accounting.** The chain
layer only mirrors deposits in and pushes *aggregate* settlements out; no per-job event touches
the chain. Everything runs behind the `ChainClient` seam, so with `GRIDIX_CHAIN_ENABLED=false`
(the default) nothing makes an RPC and the whole suite is hermetic.

## Money model

```
 developer                         GridixEscrow (on-chain)
    │ deposit USDC ───────────────────────► balanceOf(dev) += amount
    │                                          │  Deposited event
    │                     watcher (N confirmations)
    │                                          ▼
    │                        ledger: protocol → developer   (developer spendable ↑)
    │
 POST /jobs  ── hold_escrow ─► ledger: developer → escrow        (OFF-CHAIN)
 job done    ── settle      ─► ledger: escrow → provider + protocol fee   (OFF-CHAIN)
 job failed  ── refund      ─► ledger: escrow → developer        (OFF-CHAIN)
                                           │
 settlement engine (aggregate, periodic):  │
   • depositSettlement + settleBatch ──► GridixStaking: credit provider earnings on-chain
   • escrow.debit(dev, consumed)      ──► GridixEscrow: pull consumed escrow → treasury
 provider   ── withdraw ─────────────────► pulls its own earnings (pays its own gas)
```

Reconciliation proves the two sides never drift:

* **developer:** `escrow.balanceOf(wallet)` == `developer_free + escrow_held + consumed −
  confirmed_debits` (every term cancels to `deposits − withdrawals − debits`).
* **provider:** recorded `Settled` (confirmed `ProviderSettlement`) == observed `Settled` events,
  and never exceeds off-chain earnings (over-pay guard).

Any nonzero divergence sets `gridix_chain_ledger_divergence`, tripping the `ChainLedgerDivergence`
Alertmanager rule (same delivery path proven in Session 12.7).

## Settlement trigger (the documented choice)

A `settleBatch` fires when **either** condition holds, whichever comes first:

| Trigger | Value | Why |
|---|---|---|
| **Threshold** | total unsettled earnings ≥ `GRIDIX_SETTLEMENT_THRESHOLD_USDC` (default 100) | Fill the batch so one tx amortises gas across many payees (~50% saving measured in `contracts/EVIDENCE.md`). |
| **Interval** | `GRIDIX_SETTLEMENT_INTERVAL_SECONDS` since the last batch (default 3600) | A floor so a small balance never waits indefinitely for the threshold. |

Threshold-first keeps gas efficient under load; the interval bounds worst-case payout latency
when volume is low.

## Idempotency (no double-pay across a crash)

1. The batch is recorded **durably before broadcast**: a `ChainSettlement` row (reserved nonce)
   plus one `ProviderSettlement` row per payee. Those rows *reserve* the earnings — the next cycle
   subtracts them, so a crash between "record" and "confirm" can never re-select the same earnings.
2. Recovery re-checks the existing row's receipt; a re-broadcast reuses the **same reserved
   nonce**, so the chain admits at most one tx (a stuck tx is replaced, not duplicated).
3. A reverted tx **releases** its reservation (rows deleted) so the earnings settle in a later
   batch.

## Reorg handling

The watcher applies a ledger effect only once its block is `GRIDIX_CHAIN_CONFIRMATIONS` deep
(default 3). Each scan re-verifies recent block hashes; an orphaned block's events are dropped and,
if their effect was already applied, reversed with a compensating (append-only, balanced) posting.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `GRIDIX_CHAIN_ENABLED` | `false` | Master switch; false = fiat-only (`FiatStub`), no RPC. |
| `GRIDIX_CHAIN_RPC_URL` | — | JSON-RPC endpoint (use one that serves log history for catch-up). |
| `GRIDIX_ESCROW_ADDRESS` / `GRIDIX_STAKING_ADDRESS` / `GRIDIX_USDC_ADDRESS` | — | Contract addresses. |
| `GRIDIX_CHAIN_SIGNER` | `local` | `kms` (key in AWS KMS, never in the process) or `local` (key in memory). **Startup refuses `local` when `GRIDIX_ENV` is not `dev`.** |
| `GRIDIX_CHAIN_KMS_KEY_ID` / `GRIDIX_CHAIN_KMS_REGION` | — | KMS key id/ARN/alias and region, when `chain_signer=kms`. |
| `GRIDIX_COORDINATOR_PRIVATE_KEY` | — | Signs `debit` / `settleBatch` / `depositSettlement`. **Dev only** (`chain_signer=local`); leave empty under KMS. |
| `GRIDIX_CHAIN_CONFIRMATIONS` | `3` | Confirmations before an event/receipt is final. |
| `GRIDIX_CHAIN_START_BLOCK` | `0` | Deploy block for a fresh watcher cursor (0 = start at head). |
| `GRIDIX_CHAIN_LOG_WINDOW` | `500` | Max blocks per `eth_getLogs` (public RPCs cap wide ranges). |
| `GRIDIX_SETTLEMENT_THRESHOLD_USDC` / `GRIDIX_SETTLEMENT_INTERVAL_SECONDS` | `100` / `3600` | Batch trigger. |
| `GRIDIX_RECONCILE_INTERVAL_SECONDS` | `300` | Reconciliation cadence. |

Install the driver with the optional extra: `pip install '.[chain]'` (web3, lazy-imported).
KMS signing additionally needs `aioboto3` (`pip install '.[s3]'`), also lazy-imported.

## Coordinator signing: the key never enters the process (pentest H11)

The coordinator EOA holds `COORDINATOR_ROLE` on both contracts — it can debit **every**
developer's escrow. Held in process memory it is one core file, swap page, or memory dump away
from total financial compromise, and Python cannot scrub it back out: `str` is immutable,
`SecretStr` only masks `repr`, the secret manager caches values for the process lifetime, and
`eth_account` copies the key internally. So we removed the key from the process instead of
pretending to erase it.

Under `GRIDIX_CHAIN_SIGNER=kms` the coordinator holds only an address and a key id. Each
transaction is RLP-encoded locally, and its 32-byte keccak digest is sent to KMS, which returns a
signature. **There is no key in the process to dump.** `build_signer` refuses `local` outside dev,
so this cannot be forgotten on a deploy.

### Provisioning the KMS key

```bash
# The key spec is not negotiable: Ethereum is secp256k1 only.
aws kms create-key \
  --key-spec ECC_SECG_P256K1 \
  --key-usage SIGN_VERIFY \
  --description 'GRIDIX coordinator EOA'
aws kms create-alias \
  --alias-name alias/gridix-coordinator \
  --target-key-id <key-id>
```

Grant the coordinator's role **exactly** `kms:GetPublicKey` and `kms:Sign` on that key — nothing
else. Then derive the address it signs as and grant that address `COORDINATOR_ROLE` on-chain:

```bash
python -c "
import asyncio
from app.chain.signer import KmsSigner
print(asyncio.run(KmsSigner.create('alias/gridix-coordinator')).address)"
```

Set `GRIDIX_EXPECTED_COORDINATOR_ADDRESS` to that address: startup then refuses to boot if the KMS
key ever stops matching the on-chain role holder (a rotated-out or wrong key fails fast instead of
reverting on-chain).

**Rotation** is: create a new KMS key → grant the new address `COORDINATOR_ROLE` → point
`GRIDIX_CHAIN_KMS_KEY_ID` and `GRIDIX_EXPECTED_COORDINATOR_ADDRESS` at it → revoke the old role.
No secret ever moves, because there is no secret to move.

**Not yet verified against real AWS.** The reassembly (DER → address, DER → low-s (r, s) →
recovery id → RLP) is covered end to end by `tests/test_pentest_wave3_signer.py` against a fake KMS
backed by a local key, which is faithful to KMS's narrow digest-in/DER-out contract. What those
tests cannot cover is the boto3 call itself — parameter/response shapes, IAM, region resolution.
Do a testnet `settleBatch` under `chain_signer=kms` before trusting it with mainnet funds, the same
way the Docker socket proxy was proven on a real host rather than on assertion.

## Live Sepolia verification

Beyond the hermetic FakeChain suite (`tests/test_session13_chain_settlement.py`), the layer is
proven end-to-end against **live Sepolia** (chain id 11155111) at two levels. Both drivers reuse a
throwaway MockUSDC exercise pair where the coordinator key holds `COORDINATOR_ROLE` (so the
production contracts' role separation is untouched). Full tx tables + addresses live in
[`contracts/EVIDENCE.md`](../contracts/EVIDENCE.md).

**1. Raw client send-path** — `smoke/drive_settlement_sepolia.py` drives `Web3ChainClient`'s three
coordinator write methods (signing, live-chain nonce, gas estimation, ABI encoding, receipt polling
— the surface FakeChain can only fake):

| Method | Tx | Block | Effect (raw USDC) |
|---|---|---|---|
| `send_debit` | `0x3aef1644…983787d6` | 11263687 | escrow.balanceOf(dev) −3e6 |
| `send_deposit_settlement` | `0x33a8e98a…9b7fcdeada` | 11263711 | settlementPool +5e6 |
| `send_settle_batch` | `0x48702c68…931fff06` | 11263716 | earnings(provider) +2e6 |

**2. Full `SettlementEngine`** — `smoke/drive_settlement_engine_sepolia.py` runs the real engine
(durable nonce reservation, `ChainSettlement`/`ProviderSettlement` rows, the
record→broadcast→recover→confirm state machine, idempotency) over an on-disk SQLite DB against the
live chain:

| Kind | Reserved nonce | Tx | Block | Effect |
|---|---|---|---|---|
| `settle_batch` | 46 | `0x6f63d6aa…b96a3892` | 11263790 | earnings(provider) +2e6 |
| `debit` | 47 (= settle+1) | `0xc8f6b231…8fb2e0e3` | 11263792 | escrow.balanceOf(dev) −3e6 |

Three engine properties were confirmed live: **serialisation** (`_maybe_debit` skips while a tx is
in-flight, so `settle_batch` confirms before the `debit` is recorded), **monotonic nonce
reservation** across rows (debit = `settle_nonce + 1`, persisted before broadcast), and
**idempotency** (a second `tick(force=True)` after confirmation found nothing new — no double-pay).

**What stays FakeChain-only, by design.** The adversarial fault paths — crash between record and
broadcast (recovery re-sends at the same nonce), a reverted `settleBatch` releasing its reservation,
and a reorg rolling back an applied effect — cannot be forced on a public testnet on demand, so they
remain covered by FakeChain's `fail_next_send` / `force_revert` / `reorg` hooks. The live runs prove
the happy-path state machine against a real RPC; FakeChain proves it survives the failures.
