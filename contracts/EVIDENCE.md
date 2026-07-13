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
