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
| `GRIDIX_COORDINATOR_PRIVATE_KEY` | — | Signs `debit` / `settleBatch` / `depositSettlement` (via secret manager). |
| `GRIDIX_CHAIN_CONFIRMATIONS` | `3` | Confirmations before an event/receipt is final. |
| `GRIDIX_CHAIN_START_BLOCK` | `0` | Deploy block for a fresh watcher cursor (0 = start at head). |
| `GRIDIX_CHAIN_LOG_WINDOW` | `500` | Max blocks per `eth_getLogs` (public RPCs cap wide ranges). |
| `GRIDIX_SETTLEMENT_THRESHOLD_USDC` / `GRIDIX_SETTLEMENT_INTERVAL_SECONDS` | `100` / `3600` | Batch trigger. |
| `GRIDIX_RECONCILE_INTERVAL_SECONDS` | `300` | Reconciliation cadence. |

Install the driver with the optional extra: `pip install '.[chain]'` (web3, lazy-imported).
