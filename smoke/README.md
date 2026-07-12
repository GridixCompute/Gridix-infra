# P0 Smoke Test — assets & runbook

These assets execute **P0 of `reference/GAP_CLOSURE_RUNBOOK.md`**: prove one job runs end
to end on a real Docker host with real isolation and a balanced ledger. They cannot run in
the build sandbox (no Docker) — run them on a **local Docker machine first**, then RunPod.

Everything here matches the agent's real container contract (`agent/agent.py`):
input is mounted read-only at `/gridix/input` (`GRIDIX_INPUT`), output is written to
`/gridix/output/result` (`GRIDIX_OUTPUT`), and every container runs `--user 65534:65534
--read-only --network none --cap-drop ALL`.

## Files

| File | Purpose |
|------|---------|
| `scripts/run.py` | Happy path: writes `sha256(input)` — deterministic, so it also serves as a canary / quorum vote |
| `scripts/netprobe.py` | Egress probe: writes `BLOCKED` (isolated ✅) or `REACHED` (escaped ❌) |
| `scripts/sleeper.py` | Timeout probe: sleeps 600s, must be killed at the job timeout |
| `Dockerfile` | Builds all three variants via `--build-arg SCRIPT=` |
| `seed_stake.py` | Funds provider stake (no HTTP endpoint exists — see note below) |
| `drive_smoke.py` | Orchestrates the whole happy path + ledger assertions |

## Prerequisites

```bash
# from repo root, on a Docker host
docker compose up --build            # P0.1 — api + postgres + redis + scheduler
curl -sf localhost:8000/health       # must be 200

docker build -f smoke/Dockerfile --build-arg SCRIPT=run.py      -t gridix-smoke .
docker build -f smoke/Dockerfile --build-arg SCRIPT=netprobe.py -t gridix-smoke-netprobe .
docker build -f smoke/Dockerfile --build-arg SCRIPT=sleeper.py  -t gridix-smoke-sleeper .

pip install httpx                    # the driver needs it (or use the repo .venv)
```

## Run

```bash
python smoke/drive_smoke.py          # P0.3 happy path → expects completed + balanced ledger
python smoke/drive_smoke.py --egress # P0.4 isolation  → expects result BLOCKED
python smoke/drive_smoke.py --timeout # P0.4 timeout   → expects failed/timeout, no leftover container
```

The driver registers the provider and prints the exact `agent.py` command; start the agent
in another terminal, press Enter, and it submits + watches the job to a terminal state.

## Verify hardening by hand (P0.4)

While a job is running (`docker ps`), inspect the container directly:

```bash
cid=$(docker ps --filter "name=gridix-" -q | head -1)
docker inspect "$cid" | jq '.[0].HostConfig | {NetworkMode, Memory, CpuQuota, ReadonlyRootfs, CapDrop, PidsLimit}'
docker inspect "$cid" | jq '.[0].Config.User'   # must not be "0" / root
```

Expect `NetworkMode=none`, `ReadonlyRootfs=true`, `CapDrop=["ALL"]`, `Memory`/`CpuQuota`
set (not 0), `PidsLimit` set, `User="65534:65534"`.

## Two things this will surface (both flagged in the runbook)

1. **Non-root output-mount permission.** The container writes as uid 65534 to the
   agent-created output dir. If that dir isn't writable by 65534, `run.py` exits 3 with a
   clear message and the job fails with empty output. Fix in the **agent**: make the job's
   output dir group/world-writable (e.g. `out_dir.chmod(0o777)` after `mkdir`) or run
   containers as the agent's own uid. This is the first bug you're likely to hit.

2. **Stake has no HTTP path.** `ReputationMatcher` (the production matcher) refuses
   providers below `min_provider_stake` (100), and nothing exposes stake funding over the
   API — `seed_stake.py` writes it through the ledger directly. Before mainnet this needs a
   real funding flow (deposit → escrow → stake), tracked separately from P0.

## Not covered here

These assets use K=1. K>1 (redundant execution) is fixed and covered by
`tests/test_session5_redundancy_http.py`: all K providers are polled → quorum settles →
dissenter slashed, and a provider dying mid-run is reaped per-attempt so the surviving
majority still settles (or the developer is refunded if no majority remains). Remaining
trade-off: a K>1 job decides on its first assignment round — it is not requeued for a fresh
round if providers die (it fails + refunds instead). Round-level retry for K>1 is a possible
future refinement.
