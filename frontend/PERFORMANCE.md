# Frontend performance budget (Session 13.4)

Budgets we hold the app to. CI builds print per-route First Load JS; a regression
that blows the budget should be treated as a bug, not normalised.

## Budgets

| Metric                    | Budget   | Notes                                          |
| ------------------------- | -------- | ---------------------------------------------- |
| First Load JS (per route) | < 200 KB | The bytes a cold visitor downloads for a route |
| LCP (main pages)          | < 2.5 s  | Largest Contentful Paint                       |
| Lighthouse (main pages)   | ≥ 90     | Performance category                           |

## How we stay under budget

- **Shared baseline ~103 KB** — React, Next, TanStack Query, and wagmi core live
  in the shared chunk. Every authenticated route pays this once.
- **Wallet write paths are lazy** — `DepositWithdraw`, `StakePanel` and
  `EarningsPanel` pull in `wagmi/actions` (`writeContract` /
  `waitForTransactionReceipt`). They're loaded with `next/dynamic({ ssr: false })`
  so that code ships only when a signed-in user opens the deposit / stake panel,
  not on first paint of `/billing` or `/provider/earnings`.
- **Images** go through `next/image` (responsive, lazy, modern formats).

## Current First Load (representative)

Non-wallet routes sit ~103–125 KB. The two wallet routes are the heaviest and
stay under budget:

| Route                | First Load JS |
| -------------------- | ------------- |
| `/dashboard`         | ~122 KB       |
| `/jobs/new`          | ~118 KB       |
| `/billing`           | ~177 KB       |
| `/provider/earnings` | ~143 KB       |

Re-measure with `pnpm build` (the route table is printed at the end).
