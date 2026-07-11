"""API-key generation and hashing.

Keys are shown to the caller exactly once at registration. Only a keyed HMAC-SHA256
digest is stored, so a database leak does not expose usable credentials. Lookups are by
digest, which is deterministic under a fixed ``secret_key``.
"""

import hashlib
import hmac
import secrets

_KEY_PREFIX = "grdx"
_TOKEN_BYTES = 32


def generate_api_key() -> str:
    """Return a fresh plaintext API key, e.g. ``grdx_<43-char-urlsafe-token>``."""
    return f"{_KEY_PREFIX}_{secrets.token_urlsafe(_TOKEN_BYTES)}"


def hash_api_key(plaintext: str, secret_key: str) -> str:
    """Return the hex HMAC-SHA256 digest used to store and look up a key."""
    return hmac.new(secret_key.encode(), plaintext.encode(), hashlib.sha256).hexdigest()


def key_prefix(plaintext: str) -> str:
    """Return a short non-secret prefix for display/identification (e.g. ``grdx_AbC1``)."""
    return plaintext[:9]


def endpoint_token(job_id: str, secret_key: str) -> str:
    """Derive the capability token that authorizes calls to a job's routed endpoint.

    Deterministic (HMAC of the job id) so it needs no storage and can be re-issued to the
    owning developer, yet is unguessable without the server secret.
    """
    return hmac.new(secret_key.encode(), f"endpoint:{job_id}".encode(), hashlib.sha256).hexdigest()


def verify_endpoint_token(job_id: str, token: str, secret_key: str) -> bool:
    """Constant-time check of an endpoint token against the derived value."""
    return hmac.compare_digest(token, endpoint_token(job_id, secret_key))
