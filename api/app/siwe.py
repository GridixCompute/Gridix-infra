"""Sign-In with Ethereum (EIP-4361) — challenge issuance and signature verification.

The wallet is the developer's identity, and the same address is its GridixEscrow
depositor: one identity, not two.

The design decision that shapes this module: **the server composes the message, the
client only signs it.** The conventional SIWE flow has the client send the message text
alongside the signature and the server parse it — which means the security-critical
fields (``domain``, ``chainId``, the address) arrive from the party being authenticated,
and every guarantee then rests on parsing them back correctly. Here the message is built
from server-side settings, stored verbatim, and verified against what was stored, so a
forged domain or a swapped chain id is not something we have to detect: it is something
the client never gets to state.

Signature recovery is delegated to ``eth_account`` (EIP-191 ``personal_sign``). We do not
hand-roll secp256k1.
"""

import secrets
from datetime import UTC, datetime, timedelta

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils.address import is_address, to_checksum_address

# EIP-4361 fixes this wording; wallets render it, and users read it. Don't improvise.
_TEMPLATE = """{domain} wants you to sign in with your Ethereum account:
{address}

{statement}

URI: {uri}
Version: 1
Chain ID: {chain_id}
Nonce: {nonce}
Issued At: {issued_at}
Expiration Time: {expires_at}"""

_STATEMENT = "Sign in to GRIDIX. This request will not trigger a transaction or cost gas."


def normalize_address(address: str) -> str | None:
    """Return the lowercase 0x-hex form of ``address``, or None if it isn't one.

    Lowercase because it is the storage form: ``developers.wallet_address`` is unique, and
    two spellings of one address must never become two accounts.
    """
    if not isinstance(address, str) or not is_address(address):
        return None
    return to_checksum_address(address).lower()


def generate_nonce() -> str:
    """A fresh, unguessable challenge nonce (EIP-4361 requires >= 8 alphanumerics)."""
    return secrets.token_hex(16)


def build_message(
    *,
    domain: str,
    uri: str,
    address: str,
    chain_id: int,
    nonce: str,
    issued_at: datetime,
    expires_at: datetime,
) -> str:
    """Compose the exact EIP-4361 string the wallet will sign.

    ``address`` is rendered EIP-55 checksummed because that is what the spec mandates and
    what wallets display; storage stays lowercase.
    """
    return _TEMPLATE.format(
        domain=domain,
        address=to_checksum_address(address),
        statement=_STATEMENT,
        uri=uri,
        chain_id=chain_id,
        nonce=nonce,
        issued_at=_iso(issued_at),
        expires_at=_iso(expires_at),
    )


def recover_signer(message: str, signature: str) -> str | None:
    """Return the lowercase address that produced ``signature`` over ``message``.

    None when the signature is malformed or unrecoverable. Callers compare the result to
    the address the challenge was issued to — never to an address the client supplied.
    """
    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=signature)
    except Exception:
        # eth_account raises a range of errors (bad hex, bad length, bad v) for what is
        # one condition to us: this signature does not verify.
        return None
    return str(recovered).lower()


def challenge_expiry(now: datetime, ttl_seconds: int) -> datetime:
    """When a freshly issued challenge stops being usable."""
    return now + timedelta(seconds=ttl_seconds)


def utcnow() -> datetime:
    """Timezone-aware now, in UTC."""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Read a stored timestamp back as UTC-aware.

    SQLite returns naive datetimes even from a ``DateTime(timezone=True)`` column, and a
    naive ``.timestamp()`` is interpreted in the machine's LOCAL zone — so on any host
    that isn't UTC, a freshly issued challenge reads back as already expired. Everything
    is written in UTC, so naive means UTC.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    """EIP-4361 timestamps are ISO-8601 with a 'Z' suffix."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
