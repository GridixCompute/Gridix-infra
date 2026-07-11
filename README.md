# GRIDIX — Backend Control Plane

GRIDIX is a decentralized AI compute network: a **centralized control plane**
(coordinator) and a **decentralized execution plane** (independent providers run an
agent that rents out GPU/CPU). Scope is deliberately constrained to **stateless,
containerized, verifiable jobs** (batch inference, render, simulation) — not distributed
training, not a trustless coordinator, and **no token/buyback/burn**. Payments settle
through a `ledger` abstraction so fiat-now / on-chain-later is a swap, not a rewrite.

## Job lifecycle

```
developer submits (image + input + resource spec)
  → API enqueues (queued)
  → scheduler matches to a capable provider (assigned, with a lease)
  → provider agent pulls the image, runs it in a hardened sandbox (running)
  → agent returns result + proof
  → coordinator verifies (canary + reputation; quorum for high-value)
  → settles payment (completed) or refunds / slashes (failed | timeout)
```

State machine: `queued → assigned → running → completed | failed | timeout`, with
leases + heartbeats so a dead node's job is reassigned.

The three hard problems and where they live:

- **Verification** → canary tasks + reputation + stake (`verification.py`,
  `reputation.py`, `canary.py`, `quorum.py`).
- **Isolation** → hardened container execution on the agent (`agent/agent.py`).
- **Reliability** → lease + heartbeat + reassignment (`assignment.py`, `scheduler.py`).

## Layout

```
api/app/
  config.py          Pydantic settings (env-driven)
  db.py              async SQLAlchemy engine + session
  models.py          the data model (7 tables)
  schemas.py         Pydantic request/response contracts
  security.py        API-key generation + HMAC hashing
  deps.py            require_developer / require_provider
  state_machine.py   the one authoritative transition() helper
  storage.py         blob storage abstraction (local | s3 seam)
  matcher.py         Capability + ReputationMatcher (stake-gated)
  assignment.py      concurrency-safe assign + lease reaper
  scheduler.py       worker process: assign + reap + canary loops
  results.py         verify → quorum → reward/slash → settle
  verification.py    verify(job, result) -> Verdict
  reputation.py      running per-provider score from events
  ledger.py          double-entry postings, balances, stake/slash
  payments.py        PaymentProvider (FiatStub) — settle/refund/escrow
  pricing.py         cost = resources × duration; escrow estimate
  ratelimit.py       rate-limit + request-size middleware
  errors.py          structured JSON error handlers
  routes/            health, registration, jobs, providers, blobs, agent, metrics
agent/               standalone provider agent (own Dockerfile)
alembic/             migrations
tests/               hermetic unit tests + tests/integration/
```

## Quick start (Docker)

```bash
cp .env.example .env          # then set GRIDIX_SECRET_KEY
docker compose up --build     # api + postgres + redis + scheduler
curl localhost:8000/health    # => 200 {"status":"ok",...}
```

Register and submit:

```bash
# Developer + provider each get a one-time API key.
curl -sX POST localhost:8000/developers -d '{"name":"Acme"}' -H 'content-type: application/json'
curl -sX POST localhost:8000/providers  -d '{"name":"Farm"}' -H 'content-type: application/json'

# Submit a job (developer key).
curl -sX POST localhost:8000/jobs -H "Authorization: Bearer $DEV_KEY" \
  -H 'content-type: application/json' \
  -d '{"image_ref":"ghcr.io/acme/infer:1","resource_spec":{"cpu_cores":2,"memory_mb":2048}}'
```

The provider agent runs on the provider's own machine (needs Docker):

```bash
cd agent && pip install -r requirements.txt
GRIDIX_API_URL=http://localhost:8000 GRIDIX_PROVIDER_KEY=$PROV_KEY python agent.py
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check . && ruff format --check .        # lint gate (zero tolerance)
pytest                                        # hermetic unit + integration tests

# Migrations round-trip against SQLite (Postgres in prod):
GRIDIX_DATABASE_URL=sqlite+aiosqlite:///./dev.sqlite3 alembic upgrade head
GRIDIX_DATABASE_URL=sqlite+aiosqlite:///./dev.sqlite3 alembic downgrade base
```

Tests are hermetic: they run against on-disk SQLite with Redis stubbed, so no live
services are required. The same models render native Postgres types (UUID, JSONB) in
production and portable fallbacks under SQLite.

## Design notes

- **One state machine.** Every `Job.status` write goes through `transition()`, which
  rejects illegal moves and stamps lifecycle timestamps. Nothing else mutates status.
- **Money is double-entry.** Value moves only through balanced `ledger_entries`
  transactions; balances are derived. `PaymentProvider` (a `FiatStub` today) is the seam
  for on-chain settlement later — the schema and call sites don't change.
- **Escrow correctness.** Worst-case cost is escrowed at submit; on verified completion
  the developer pays only the actual cost (remainder refunded) and the provider is paid
  net of the protocol fee; any failure refunds the developer in full and pays no one.
  Proven by `tests/integration/test_full_flow.py`.
- **Cheating has negative expected value.** Canaries (known-answer jobs indistinguishable
  from real work) catch liars; high-value jobs are cross-checked by quorum; a caught
  cheat is slashed for more than it could gain and its reputation collapses, starving it
  of future work. Verification is probabilistic by design — see `verification.py`.
- **Hardened by default.** The agent runs untrusted images with `--network none`,
  `--cap-drop ALL`, `--read-only`, non-root, pid/memory/cpu limits, and a hard
  wall-clock timeout. Egress and GPU are opt-in.

## Session map

The backend was built in six focused sessions; each has tests:

| Session | Scope | Tests |
|---|---|---|
| 1 | Foundation & data model, auth, health, registration | `test_session1_foundation.py` |
| 2 | Job & provider API, state machine, storage | `test_session2_jobs_providers.py` |
| 3 | Scheduler, leases, heartbeats, reaper | `test_session3_scheduler.py` |
| 4 | Sandboxed provider agent, result intake | `test_session4_agent.py` |
| 5 | Verification, reputation, canary, quorum, stake/slash | `test_session5_verification.py` |
| 6 | Ledger settlement, escrow, hardening, observability | `test_session6_ledger_hardening.py`, `integration/test_full_flow.py` |
