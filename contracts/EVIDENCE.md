# GridixEscrow — deployment & test evidence

## Tests + coverage (local)

`forge test` — **18 passed, 0 failed**, incl. the reentrancy attacker and the fuzzed
accounting invariant (512 runs). `forge coverage` for `src/GridixEscrow.sol`:

```
| File                 | % Lines         | % Statements    | % Branches    | % Funcs       |
| src/GridixEscrow.sol | 100.00% (39/39) | 100.00% (41/41) | 100.00% (7/7) | 100.00% (8/8) |
```

100% across lines / statements / branches / functions (> 95% required).

## Deployed on Sepolia (chain id 11155111)

| Field | Value |
|---|---|
| **GridixEscrow** | `0xd93076eb67ab21ae068c0ad7a6256ca6ba58f733` |
| Deploy tx | `0x5cfab65f262d5629333dc21c46af330625901363c6eb8dbcc8186530fc60711c` |
| Block | 11262619 (status success, gasUsed 814223) |
| Token (USDC) | `0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238` (Circle Sepolia USDC, `symbol=USDC`, `decimals=6`) |
| Admin (`DEFAULT_ADMIN_ROLE`) | `0x2dA408cb2899351eC948b4A3Dd438caA9Ac213e8` |
| Coordinator (`COORDINATOR_ROLE`) | `0xB54CE6FbB941E4b2A444E2E256149b6C21335532` |
| Treasury | `0x33593a59f6BD437BC5Ea2bEdEc8c115e2A949a5D` |

Explorer: https://sepolia.etherscan.io/address/0xd93076eb67ab21ae068c0ad7a6256ca6ba58f733

### On-chain verification (via `cast call`)

```
token()      == 0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238   (USDC) ✓
treasury()   == 0x33593a59f6BD437BC5Ea2bEdEc8c115e2A949a5D          ✓
hasRole(DEFAULT_ADMIN_ROLE, admin)        == true                    ✓
hasRole(COORDINATOR_ROLE,  coordinator)   == true                    ✓
hasRole(COORDINATOR_ROLE,  admin)         == false  (roles separate) ✓
hasRole(DEFAULT_ADMIN_ROLE, coordinator)  == false                   ✓
balanceOf(anyone)                         == 0                       ✓
```

The coordinator role is held by an address distinct from the admin — debiting funds is
separated from administration, as required.

> The deployer is a throwaway testnet key funded from a faucet; its private key lives only in
> `contracts/.env` (gitignored) and controls no mainnet value.

---

# GridixStaking (provider side — Prompt B)

## Tests + coverage (local)

`forge test` — **46 tests pass total** (18 escrow + 28 staking), incl. reentrancy on both
`withdraw` and `settleBatch`, slash→dispute→overturned/upheld, cooldown enforcement, array
validation, and a fuzzed stake-accounting invariant (512 runs). Coverage:

```
| src/GridixEscrow.sol  | 100.00% lines | 100.00% statements | 100.00% branches | 100.00% funcs |
| src/GridixStaking.sol | 100.00% lines | 100.00% statements | 100.00% branches | 100.00% funcs |
```

## Batch settlement gas — measured

`test_Gas_SettleBatch_vs_Individual` (50 providers, disjoint fresh addresses so both paths pay
the same cold-storage cost):

| | Gas |
|---|---|
| `settleBatch(50)` — one tx | **1,243,032** |
| 50 separate txs (exec + 21000 intrinsic each) | **2,568,779** |
| **Saved** | **1,325,747 (~51.6%)** |

Batching N payouts into one transaction roughly halves the gas, and the saving grows with N
(each avoided transaction is 21,000 intrinsic gas alone). Providers withdraw their own earnings,
so they pay their own gas — the coordinator never subsidizes it.

## Deployed on Sepolia (chain id 11155111)

| Field | Value |
|---|---|
| **GridixStaking** | `0x72089171441d05ad2a64777177fF2864a9703822` |
| Deploy tx | `0xe1fbb0a363ba86ff3b5a67086f404dfa6e5505b3fc33531aa7af62b6e4a22b0c` |
| Block | 11262679 (status success, gasUsed 1,451,793) |
| Token (USDC) | `0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238` (6 decimals) |
| Admin | `0x2dA408cb2899351eC948b4A3Dd438caA9Ac213e8` |
| Coordinator (`COORDINATOR_ROLE`) | `0xB54CE6FbB941E4b2A444E2E256149b6C21335532` |
| Arbiter (`ARBITER_ROLE`) | `0x62992690F7393025bb7754AC718c8a04B47512D4` |
| Treasury | `0x33593a59f6BD437BC5Ea2bEdEc8c115e2A949a5D` |
| minStake | 100000000 (100 USDC) |
| cooldownPeriod | 604800 (7 days > detection + dispute window) |

Explorer: https://sepolia.etherscan.io/address/0x72089171441d05ad2a64777177fF2864a9703822

### On-chain verification (via `cast call`)

```
token()==USDC ✓  treasury()==treasury ✓  minStake==100e6 ✓  cooldownPeriod==604800 ✓
hasRole(DEFAULT_ADMIN_ROLE, admin)       == true            ✓
hasRole(COORDINATOR_ROLE,  coordinator)  == true            ✓
hasRole(ARBITER_ROLE,      arbiter)      == true            ✓
hasRole(ARBITER_ROLE,      coordinator)  == false (slasher != arbiter) ✓
hasRole(COORDINATOR_ROLE,  admin)        == false           ✓
```

Three separate roles: the party that slashes (coordinator) cannot resolve its own dispute
(arbiter), and neither is the admin.

---

# Live on-chain exercise (Sepolia, 17/17 tx OK)

To check for runtime errors, every function of both contracts was exercised with real Sepolia
transactions (`script/Exercise.s.sol`). Because the production deployments use Circle USDC
(unmintable) and separate role keys, the exercise deployed a fresh MockUSDC + a fresh pair with
the deployer holding all roles — same contract code. **All 17 transactions succeeded (status
0x1), no reverts:**

```
 1 deploy MockUSDC        6 escrow.deposit      11 depositSettlement   16 unstake
 2 deploy GridixEscrow    7 escrow.debit        12 settleBatch(2)      17 completeUnstake
 3 deploy GridixStaking   8 escrow.withdraw     13 staking.withdraw
 4 usdc.mint              9 approve             14 slash
 5 approve               10 stake               15 resolveDispute(overturned)
```

Final state consistent: escrow.balanceOf=0 (100 deposited − 30 debited − 70 withdrawn),
stake=100e6 (200 staked, 50 slashed→dispute overturned→returned, 100 unstaked+claimed),
earnings(other)=10e6 (settled, unwithdrawn). Exercise contracts (throwaway, MockUSDC):
GridixEscrow `0x04B237e8b5F3de59F02C3E61007351Eb5d8CA09B`, GridixStaking
`0xfc51f5439c96B47B37304BBd63147ef53d15D01F`.

---

# Multi-wallet stake/unstake churn (Sepolia — 41 stake + 40 unstake, 0 reverts)

To check for runtime errors under repeated use from many independent callers, stake/unstake was
driven from **10 distinct fresh wallets**, each funded from the contract-creator wallet
(`0x2dA408cb2899351eC948b4A3Dd438caA9Ac213e8`). Reused the live exercise pair (no redeploy):
GridixStaking `0xfc51f5439c96B47B37304BBd63147ef53d15D01F` (unpaused, cooldown 0) over MockUSDC
`0x48d9eb22261094f9C2F31587daD06fa80df6d23B`. Each wallet minted its own MockUSDC, approved once,
then looped `stake(5 USDC)`→`unstake(5 USDC)` as far as its ETH slice allowed; leftover ETH was
swept back to the creator.

Budget-bounded by the creator's ~0.0284 test ETH at a ~3.7–4.7 gwei base fee (which is why the
per-wallet loop count is 4, not 10 — the target was scaled to fit the on-hand faucet balance).

**Result — every transaction that reached the chain succeeded (status 0x1), zero reverts:**

```
on-chain totals:  41 stake tx   +   40 unstake tx      (81 stake/unstake ops)
total wallet txs: 121  (10 mint + 10 approve + 41 stake + 40 unstake + 20 sweep)
per wallet:       4 stake / 4 unstake  (w2: 5 stake — one extra from an RPC-retry re-submit)
net ETH spent:    0.02836 -> 0.00159  (~0.0268 ETH, incl. sweep-backs)
```

Accounting verified directly on-chain afterwards: every wallet's cooling bucket
(`unstakingOf`) equals `unstakes × 5 USDC` exactly (10 × 20 USDC cooling), and active stake is 0
(w2: 5 USDC, its one extra stake) — a mid-sequence revert would have left ragged state, so the
clean multiples confirm no stake/unstake failed. Sample unstake tx
`0xbd39f8facac2267bf652e71d418c019a8a6d34d2eb7b530551faa0db85693215` (status 1). The only
non-successful events were client-side gas-estimation refusals once a wallet's ETH ran below one
tx's worth — the loop's intended budget stop, not contract reverts.
