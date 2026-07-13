#!/usr/bin/env bash
# Provision Vault for the GRIDIX backend (operator step, run once with an admin token — NOT the
# backend's token). Creates the least-privilege read policy, an AppRole bound to it with TTLs,
# and writes the managed secrets to secret/gridix. Prints ROLE_ID / SECRET_ID for the backend.
#
# Secrets come from the environment so none is ever hardcoded here:
#   GRIDIX_SECRET_KEY, GRIDIX_KEK, GRIDIX_ATTESTATION_SECRET, GRIDIX_COORDINATOR_PRIVATE_KEY
# Requires: VAULT_ADDR + VAULT_TOKEN (an admin/root token, used ONLY for this provisioning).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${VAULT_ADDR:?set VAULT_ADDR}"; : "${VAULT_TOKEN:?set VAULT_TOKEN}"
VAULT="${VAULT_BIN:-vault}"

# 1) least-privilege read-only policy
"$VAULT" policy write gridix-read "$HERE/gridix-read.hcl"

# 2) AppRole auth with short TTLs (enable is idempotent)
"$VAULT" auth enable approle 2>/dev/null || true
"$VAULT" write auth/approle/role/gridix \
  token_policies=gridix-read \
  token_ttl=1h token_max_ttl=4h \
  secret_id_ttl=24h secret_id_num_uses=0

# 3) write the managed secrets (values from env; the coordinator key is the crown jewel)
"$VAULT" kv put secret/gridix \
  GRIDIX_SECRET_KEY="${GRIDIX_SECRET_KEY:?}" \
  GRIDIX_KEK="${GRIDIX_KEK:?}" \
  GRIDIX_ATTESTATION_SECRET="${GRIDIX_ATTESTATION_SECRET:?}" \
  GRIDIX_COORDINATOR_PRIVATE_KEY="${GRIDIX_COORDINATOR_PRIVATE_KEY:?}" >/dev/null

# 4) hand the backend its AppRole credentials (role_id is stable; secret_id is freshly minted)
ROLE_ID="$("$VAULT" read -field=role_id auth/approle/role/gridix/role-id)"
SECRET_ID="$("$VAULT" write -f -field=secret_id auth/approle/role/gridix/secret-id)"
echo "GRIDIX_VAULT_ROLE_ID=$ROLE_ID"
echo "GRIDIX_VAULT_SECRET_ID=$SECRET_ID"
