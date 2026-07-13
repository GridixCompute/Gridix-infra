# Least-privilege policy for the GRIDIX backend's Vault AppRole.
# The backend only CONSUMES secrets: it may read exactly its own KV-v2 secret and nothing else.
# No write, no list, no access to any other path, no auth/sys administration.

path "secret/data/gridix" {
  capabilities = ["read"]
}

# KV-v2 keeps metadata on a sibling path; read-only is enough to resolve the latest version.
path "secret/metadata/gridix" {
  capabilities = ["read"]
}
