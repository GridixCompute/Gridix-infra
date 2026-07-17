"""API-key generation and hashing.

Keys are shown to the caller exactly once at registration. Only a keyed HMAC-SHA256
digest is stored, so a database leak does not expose usable credentials. Lookups are by
digest, which is deterministic under a fixed ``secret_key``.

**Why there is no per-key salt** (pentest H5, reviewed and accepted — do not "fix" this
without reading the argument). A salt exists to stop precomputation against *guessable*
secrets. These keys are not guessable: ``generate_api_key`` draws 32 bytes from
``secrets`` — 256 bits of entropy — so recovering a plaintext from its digest means
brute-forcing 2**256, salt or no salt. The finding's stated impact ("if the HMAC key
leaks, all API keys can be recomputed offline") does not hold against a one-way HMAC over
a 256-bit random preimage. ``secret_key`` already acts as a global pepper, which is what
actually defeats cross-deployment rainbow tables. The residual risk — HMAC key **plus DB
write access** lets an attacker mint a key they know — is not addressed by a salt either
(they would simply choose their own). Meanwhile a per-key salt would force lookups off the
unique indexed digest and onto the prefix, and bcrypt/Argon2 would put a work factor on
every authenticated request, buying nothing here. Same reasoning as GitHub's and Stripe's
token storage: high-entropy tokens get a fast keyed hash, not a password KDF.

What *was* real in that area is L1: the plaintext is attacker-supplied, so its length is
capped before it reaches the HMAC (see ``MAX_API_KEY_BYTES``).
"""

import hashlib
import hmac
import secrets

_KEY_PREFIX = "grdx"
_TOKEN_BYTES = 32

# An issued key is ``grdx_`` + 43 urlsafe chars = 48 bytes. Anything wildly longer was
# never issued by us, so refuse it before spending CPU on the HMAC — otherwise a caller
# can make every request hash megabytes of attacker-chosen data (pentest L1).
MAX_API_KEY_BYTES = 512


def generate_api_key() -> str:
    """Return a fresh plaintext API key, e.g. ``grdx_<43-char-urlsafe-token>``."""
    return f"{_KEY_PREFIX}_{secrets.token_urlsafe(_TOKEN_BYTES)}"


def hash_api_key(plaintext: str, secret_key: str) -> str:
    """Return the hex HMAC-SHA256 digest used to store and look up a key.

    Raises ``ValueError`` if ``plaintext`` is too long to be a key we ever issued; callers
    treat that as an authentication failure rather than hashing bulk input (L1).
    """
    raw = plaintext.encode()
    if len(raw) > MAX_API_KEY_BYTES:
        raise ValueError("api key exceeds the maximum plausible length")
    return hmac.new(secret_key.encode(), raw, hashlib.sha256).hexdigest()


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
