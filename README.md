# GRIDIX — Backend Control Plane

GRIDIX is a decentralized AI compute network: a **centralized control plane**
(coordinator) and a **decentralized execution plane** (independent providers run an agent
that rents out GPU/CPU). Scope is deliberately constrained to **stateless, containerized,
verifiable jobs** (batch inference, render, simulation) — not distributed training, not a
trustless coordinator, and **no token/buyback/burn**. Payments settle through a `ledger`
abstraction so fiat-now / on-chain-later is a swap, not a rewrite.

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

State machine: `queued → assigned → running → completed | failed | timeout`, with leases +
heartbeats so a dead node's job is reassigned. Every `Job.status` write goes through the
one authoritative `transition()` helper, which rejects illegal moves and stamps lifecycle
timestamps.

The three hard problems and where they live:

- **Verification** → canary tasks + reputation + stake (`verification.py`, `reputation.py`,
  `canary.py`, `quorum.py`).
- **Isolation** → hardened container execution on the agent (`agent/agent.py`).
- **Reliability** → lease + heartbeat + reassignment (`assignment.py`, `scheduler.py`).

## Capabilities

**Core control plane**
- API-key auth (HMAC-hashed, shown once), developer/provider registration, `/health`
  (DB + Redis), structured JSON errors, rate-limit + request-size middleware.
- Job submit/list/read, provider capability declaration, blob storage abstraction.
- Concurrency-safe scheduler (SELECT … FOR UPDATE SKIP LOCKED) with leases, heartbeats, a
  reaper that reassigns dead-node jobs, and periodic canary injection.

**Verification, reputation & economics**
- `verify(job, result) → Verdict`: proof well-formedness, exit/timeout, and exact
  canary-answer match. Reputation is a running per-provider score fed back into matching.
- Redundant execution for high-value jobs settles by **quorum**; agreers are paid,
  disagreers slashed.
- Double-entry `ledger`; escrow at submit, settle on verified completion, refund on
  failure; per-job **data-cost** line item from measured bytes. `PaymentProvider`
  (`FiatStub`) is the on-chain seam.

**Connectivity & NAT traversal**
- Robust long-poll control channel with presence (`connected_at` / `last_seen`), jittered
  backoff, and idle keepalive.
- Standalone **relay** (`relay.py`): agents hold one persistent outbound tunnel; the
  coordinator routes requests to a specific NAT'd provider and reads the reply back.
- Direct-path negotiation with transparent relay fallback; **endpoint-style jobs** get a
  coordinator-issued, token-authed URL forwarded to a container port; per-provider
  bandwidth accounting; fast tunnel-drop detection that drains and reassigns.

**Data movement & artifacts**
- Content-addressed storage (sha256) with a real S3 backend over a pluggable object store;
  integrity verified on every download.
- Provider-side LRU artifact cache (skip re-downloads), chunked/resumable uploads with
  digest-verified assembly, warm-cache locality preference in the matcher, and an
  (off-by-default) peer-distribution interface.

**Confidential compute & secrets**
- Per-job data tiers (`public` / `encrypted_at_rest` / `confidential_tee`); envelope
  encryption so the coordinator stores ciphertext only.
- Job-scoped key brokering to the assigned agent for the job's lifetime; confidential-tee
  jobs schedule only to attested-TEE providers and release keys only after a valid remote
  attestation; short-lived runtime secrets, never persisted or logged. Per-tier threat
  model in `docs/THREAT_MODEL.md`.

**Dispute resolution & slashing governance**
- Slashes are **held, not burned**, pending resolution; every slash links reproducible
  evidence with an on-chain-ready commitment hash.
- Automated first-line adjudication, human review queue with audit-logged rulings, quorum
  re-vote for redundant jobs, and graduated penalties that escalate repeat offenders while
  sparing honest failures.

**Onboarding, benchmarking & health**
- Signed hardware benchmark at onboarding, validated against declared specs; trust source
  (attested / benchmark / self-report); continuous health telemetry that flags degraded
  providers; anti-spoofing (shared-GPU collisions, inflated capacity). The matcher uses
  measured health, not self-declared specs alone.

**Production operations**
- Secret management abstraction (env now, Vault/KMS seam) with zero-downtime KEK rotation.
- Expand-only migrations (enforced by a test), tamper-evident hash-chained audit log,
  Prometheus `/metrics`, symptom alerts + runbooks/SLOs, ledger-integrity DR check, and
  graceful degradation (a Redis outage loses no job and double-charges no one). CI runs
  lint, migrations, unit+integration tests, image builds, and dependency/image scans.

## Layout

```
api/app/
  config.py          Pydantic settings (env-driven)
  db.py  models.py   async SQLAlchemy engine/session + the data model
  schemas.py         Pydantic request/response contracts
  security.py deps.py  API-key hashing; require_developer/provider/internal
  state_machine.py   the one authoritative transition() helper
  matcher.py         capability + reputation matcher (stake / presence / health gated)
  assignment.py scheduler.py   assign, lease reaper, drain, recovery, canary loops
  results.py verification.py reputation.py quorum.py canary.py   verify → quorum → settle/slash
  ledger.py payments.py pricing.py   double-entry money, escrow, settle/refund, data cost
  disputes.py adjudicate.py penalties.py fraud_proof.py   dispute lifecycle + governance
  storage.py chunked.py bandwidth.py peer_distribution.py   artifacts, resumable transfer, egress
  crypto.py key_broker.py attestation.py secrets_broker.py   confidential compute
  benchmark.py health.py antispoof.py   onboarding, telemetry, anti-spoofing
  secret_manager.py audit_log.py alerts.py   ops: secrets, tamper-evident audit, alerting
  relay.py relay_client.py paths.py presence.py   connectivity / NAT traversal
  ratelimit.py errors.py logging.py   hardening & observability
  routes/            health, registration, jobs, providers, blobs, uploads, agent,
                     endpoints, disputes, metrics
agent/               standalone provider agent (hardened sandbox, cache, relay tunnel)
alembic/             migrations (expand-only)
docs/                THREAT_MODEL, DEPLOY, DR, RUNBOOKS
tests/               hermetic unit tests + tests/integration/ (full flow + chaos)
relay:               separate service (uvicorn app.relay:app)
```

## Quick start (Docker)

```bash
cp .env.example .env          # then set GRIDIX_SECRET_KEY
docker compose up --build     # api + postgres + redis + scheduler + relay
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
# optionally set GRIDIX_RELAY_URL=ws://relay:8100/relay/agent to tunnel through the relay
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
production and portable fallbacks under SQLite. Infrastructure-bound behavior (real NAT
traversal, S3/MinIO, TEE attestation, Vault/KMS, PITR restore) is implemented behind clean
seams and validated on real infrastructure.

## Design notes & invariants

- **One state machine.** Every status change goes through `transition()` — nothing else
  mutates `Job.status`.
- **Money is double-entry.** Value moves only through balanced `ledger_entries` groups;
  balances are derived. `verify_ledger_integrity()` confirms zero discrepancy (used as the
  DR restore check).
- **Escrow correctness.** Worst-case cost is escrowed at submit; on verified completion the
  developer pays only the actual cost (remainder refunded) and the provider is paid net of
  the protocol fee; any failure refunds the developer in full and pays no one.
- **Cheating has negative expected value.** Canaries catch liars, high-value work is
  cross-checked by quorum, and a caught cheat is slashed for more than it could gain and
  loses the reputation that earns it work. Verification is probabilistic by design.
- **Hardened by default.** The agent runs untrusted images with `--network none`,
  `--cap-drop ALL`, `--read-only`, non-root, pid/memory/cpu limits, and a hard wall-clock
  timeout. Egress, GPU, and published ports are opt-in.

Two invariants hold across the whole system and are asserted under induced churn
(`tests/integration/test_chaos.py`): **the ledger stays balanced**, and **no job is
silently lost** — every job ends terminal or is reassigned.

## Testing

```bash
pytest -q                    # ~200 hermetic unit + integration tests
pytest tests/integration     # full happy path, failure paths, chaos/churn
```

Run the `pytest` binary, never `python -m pytest`. The `-m` form prepends the current
working directory to `sys.path`, so a broken or missing import can resolve against the
source tree and pass locally while CI — which installs the package and runs the `pytest`
binary — fails. Matching CI's invocation exactly keeps the local gate as strict as the
remote one; a looser local gate is what let a broken import through once.

Key end-to-end guarantees: `tests/integration/test_full_flow.py` (submit → assign → run →
verify → settle, with exact ledger balances) and `tests/integration/test_chaos.py` (node
churn: no job lost, ledger balanced).
