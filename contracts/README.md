# GRIDIX on-chain — developer side

`GridixEscrow` — the developer-facing USDC escrow. Developers deposit USDC to fund jobs, the
coordinator debits the cost of verified work, and developers withdraw whatever is unspent.
(Provider payouts are a separate contract — Prompt B — and are intentionally not here.)

Built with Foundry + OpenZeppelin v5 (no hand-rolled primitives). Solidity 0.8.24.

## Contract

`src/GridixEscrow.sol`

- `deposit(uint256)` — pull USDC from the caller (SafeERC20), credit their escrow balance.
- `withdraw(uint256)` — return unspent escrow to the caller.
- `debit(address dev, uint256)` — **COORDINATOR_ROLE only** — move `amount` from `dev`'s
  escrow to the treasury.
- `balanceOf(address) view`, `setTreasury(address)` (admin), `pause()/unpause()` (admin).

Security posture:
- **AccessControl** with two distinct roles — `DEFAULT_ADMIN_ROLE` (manage roles, pause,
  treasury) and `COORDINATOR_ROLE` (debit). Not a single owner.
- **ReentrancyGuard** on every token-moving function; **Pausable**; **SafeERC20**.
- **Checks-effects-interactions** everywhere: balances change before any token transfer.
- Accounting is unit-exact (only add/sub, no division) so USDC's 6 decimals never round.
- Invariant: `token.balanceOf(escrow) == Σ balanceOf(dev)`. USDC-only (no fee-on-transfer).

## Build & test

```bash
forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts@v5.1.0 --no-git
forge build
forge test -vvv
forge coverage
```

Test suite (`test/GridixEscrow.t.sol`): happy path (deposit→debit→withdraw), a reentrancy
attacker via a hostile ERC20 (must revert), debit by non-coordinator (revert), withdraw over
balance (revert), deposit/withdraw/debit while paused (revert), USDC 6-decimal exactness, and
a fuzzed balance-accounting invariant. **18 tests pass; 100% coverage** (lines/statements/
branches/functions).

## Deploy (Sepolia)

```bash
cp .env.example .env   # fill PRIVATE_KEY (funded), RPC, USDC + role addresses
source .env
forge script script/Deploy.s.sol --rpc-url "$SEPOLIA_RPC_URL" --broadcast
```

Deployed address is recorded in `EVIDENCE.md`.
