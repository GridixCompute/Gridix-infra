# Secrets in HashiCorp Vault

The `vault` secret backend (`app.secret_manager.VaultSecretManager`) sources GRIDIX's secrets from
HashiCorp Vault instead of `.env` or mounted files. It exists for one secret above all: the
**coordinator private key**, which holds `COORDINATOR_ROLE` and can `debit` **every** developer's
on-chain escrow. That key must never sit in a `.env` on a box — a box can OOM, vanish, or leak, and
the key would go with it. In Vault the key lives in a hardened store, is read once at startup over
an authenticated channel, and never lands in `Settings`, a log line, a metric, or an error message.

## Why Vault (not just env/file)

`env` and `file` remain valid for lower-value secrets and local dev. Vault adds: central storage
decoupled from any single host, per-consumer authentication with TTLs, a least-privilege policy per
app, an audit log of every access, and rotation without redeploying. HashiCorp Vault was chosen over
a cloud KMS because it self-hosts (runs anywhere, including a single container) and is trivial to
stand up for testing — see the live verification below.

## What the backend reads

All managed secrets live in **one** KV-v2 secret at `secret/data/gridix`, each keyed by its env
name:

| Vault key | Used for |
|---|---|
| `GRIDIX_SECRET_KEY` | API-key HMAC |
| `GRIDIX_KEK` | per-job data-key brokering (Fernet) |
| `GRIDIX_ATTESTATION_SECRET` | TEE attestation root of trust |
| `GRIDIX_COORDINATOR_PRIVATE_KEY` | signs `debit` / `settleBatch` / `depositSettlement` |

`init_secrets()` authenticates, reads that path once, overlays `secret_key`/`kek`/
`attestation_secret` onto `Settings`, and validates. The coordinator key is deliberately **not**
overlaid onto `Settings` — `app.chain.bootstrap.install_chain` fetches it on demand from the
manager only when it builds the signing client, so it is never persisted on the long-lived settings
object. As defense in depth, `coordinator_private_key` is typed `SecretStr`, so even an accidental
`repr(settings)` prints `**********`.

## Backend configuration

```bash
GRIDIX_SECRET_BACKEND=vault
GRIDIX_VAULT_ADDR=https://vault.internal:8200
GRIDIX_VAULT_AUTH_METHOD=approle          # or "token"
GRIDIX_VAULT_ROLE_ID=<role id>            # AppRole (preferred)
GRIDIX_VAULT_SECRET_ID=<secret id>        # short-TTL; response-wrap in prod
# GRIDIX_VAULT_TOKEN=<periodic/TTL token> # token auth alternative — NEVER the root token
GRIDIX_VAULT_KV_MOUNT=secret              # default
GRIDIX_VAULT_SECRET_PATH=gridix           # default
# GRIDIX_VAULT_NAMESPACE=...              # Vault Enterprise only
```

Install the driver with the optional extra: `pip install '.[vault]'` (hvac, lazy-imported — the
hermetic test suite never needs it).

The `role_id`/`secret_id` (or a token) are the bootstrap "secret zero": inject them via the
environment or a mounted file. Prefer a **response-wrapped, short-TTL `secret_id`** delivered to the
process at launch so a leaked env dump doesn't hand over a long-lived credential.

## Provisioning (operator, once)

`smoke/vault/provision.sh` (run with an **admin** token, never used by the backend) creates the
least-privilege policy (`smoke/vault/gridix-read.hcl` — `read` on `secret/data/gridix` and its
metadata, nothing else), an AppRole bound to it with token/secret-id TTLs, and writes the secrets
from the environment:

```bash
export VAULT_ADDR=https://vault.internal:8200
export VAULT_TOKEN=<admin token>          # provisioning only
export GRIDIX_SECRET_KEY=... GRIDIX_KEK=... GRIDIX_ATTESTATION_SECRET=... \
       GRIDIX_COORDINATOR_PRIVATE_KEY=...
smoke/vault/provision.sh                   # prints GRIDIX_VAULT_ROLE_ID / _SECRET_ID
```

## Fail-fast

If Vault is unreachable, auth fails, or the secret path is missing/empty, `VaultSecretManager`'s
constructor raises `SecretConfigurationError`, so `init_secrets()` — called at API and scheduler
startup — kills the process at second zero. The backend **never boots with empty keys**. Error
messages carry only the address/path and the exception *type*, never a secret value.

## Rotating the coordinator key

The coordinator key is on-chain authority, so rotation is a contract operation, not just a secret
swap. **Order matters — never revoke the old role before the new key is proven working**, or
settlement stalls:

1. **Generate** a new coordinator EOA (keypair) offline.
2. **Grant** it the role on-chain, from the admin key, on **both** contracts:
   `GridixEscrow.grantRole(COORDINATOR_ROLE, newAddr)` and `GridixStaking.grantRole(...)`.
   Both keys now hold the role — a safe overlap window.
3. **Store** the new private key in Vault: `vault kv put secret/gridix
   GRIDIX_COORDINATOR_PRIVATE_KEY=<new> …` (KV-v2 keeps the prior version for rollback).
4. **Roll** the backends (they re-read Vault at startup) and **verify** the new key works: watch a
   real `settleBatch`/`debit` confirm on-chain, or run the settlement engine against it.
5. **Only then revoke** the old key on-chain: `revokeRole(COORDINATOR_ROLE, oldAddr)` on both
   contracts. The old key is now powerless even if it later leaks.
6. **Destroy** the old key material (Vault version + any offline copy).

If step 4 fails, roll back to the previous Vault version and investigate — the old role is still
active, so nothing is stuck.

**This procedure has been run for real (2026-07-14), not just documented.** On the Sepolia production
contracts the coordinator was rotated from the ownerless `0xB54C…5532` to our Vault-managed
`0xBbBe…774E9`: granted on both contracts (step 2), stored in Vault (step 3), and — because those
instances are bound to an unobtainable token (Circle Sepolia USDC, see `contracts/EVIDENCE.md`) —
step 4's *on those instances* was substituted by proving the identical bytecode + the same
Vault-sourced key on the MockUSDC exercise pair (a live Vault-signed `debit` + `settleBatch`), then
the old key was revoked (step 5). Verified on-chain: `0xB54C…5532` no longer holds the role;
`0xBbBe…774E9` does. Tx hashes in `contracts/EVIDENCE.md`. The lesson: when the deployed instances
can't be exercised (token-gated), prove the mechanism on an equivalent fundable deployment before
revoking — never revoke on faith.

## Rotating the AppRole credential

The `secret_id` is short-TTL; mint a fresh one (`vault write -f
auth/approle/role/gridix/secret-id`) and hand it to the process at next launch. The `role_id` is
stable. To rotate the bound policy, edit `gridix-read.hcl` and `vault policy write gridix-read` — the
change applies to new tokens immediately; it never widens access beyond the single read path.

## Live verification (evidence)

`smoke/vault/verify_live.py` exercises the Definition of Done against a real Vault (no Docker
needed — `vault server -dev` is a single binary). Proven on 2026-07-13 against Vault 1.15.6:

- **`up`** — backend reads `secret_key` from Vault (not env); the coordinator key is **absent from
  `Settings`** yet readable from Vault on demand; the AppRole token is **denied** both a write to its
  own path and a read of any other path (least privilege, 403).
- **`down`** — with Vault killed, `init_secrets` **fails fast**: `cannot read secrets from Vault …
  ConnectionError` — it refuses to boot rather than run with empty keys.
- **grep** — the coordinator key sentinel appears in **no** captured backend log, error, or output.

```bash
# UP
export GRIDIX_SECRET_BACKEND=vault GRIDIX_ENV=prod GRIDIX_VAULT_ADDR=http://127.0.0.1:8200 \
       GRIDIX_VAULT_AUTH_METHOD=approle GRIDIX_VAULT_ROLE_ID=... GRIDIX_VAULT_SECRET_ID=...
python smoke/vault/verify_live.py up
# DOWN (after stopping Vault)
python smoke/vault/verify_live.py down
```

`smoke/vault/verify_coordinator_wiring.py` goes one step further: with the coordinator key in Vault
and the production contract addresses + `GRIDIX_EXPECTED_COORDINATOR_ADDRESS` set, it runs the real
`init_secrets` + `install_chain` startup path and asserts the key read from Vault derives to the
expected on-chain role holder — and that a wrong expected address fails fast. Proven live on
2026-07-13 against the production deployment (coordinator rotated to
`0xBbBe5A990C8e0C9B174309d5e0E1f1C932F774E9`; grants in `contracts/EVIDENCE.md`).
