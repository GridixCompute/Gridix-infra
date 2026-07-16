"""Transaction signers for the coordinator EOA (pentest H11).

The coordinator key holds COORDINATOR_ROLE on both contracts — it can debit every
developer's escrow and move settlement funds. Holding it as process memory was the
finding: ``Account.from_key`` pins the raw key on a long-lived object, and a memory dump,
core file, or swap page leaks it. Python cannot walk that back — ``str`` is immutable,
``SecretStr`` only masks ``repr``, the secret manager caches every value for the process
lifetime, and ``eth_account`` copies the key internally. "Zero the buffer after loading"
is not implementable here; the only real fix is for the key never to enter the process.

So signing is an interface with two implementations:

* :class:`KmsSigner` — the key lives in AWS KMS (``ECC_SECG_P256K1``) and never leaves it.
  We send a 32-byte digest and get a signature back. Nothing to dump. **Production.**
* :class:`LocalKeySigner` — the old behaviour, key in process. **Dev and tests only**;
  ``chain.bootstrap.build_signer`` refuses to construct one when ``env`` is not dev.

The fiddly part is that KMS speaks X.509/DER while Ethereum speaks (v, r, s), so the
reassembly below is where bugs would hide: DER public key → address, DER signature →
low-s (r, s) → recovery id → RLP. It is covered end to end against a fake KMS backed by a
local key (tests/test_pentest_wave3_signer.py), which is faithful because KMS's observable
contract is narrow — hand it a digest, get DER back.

Those tests assert the signed transaction **recovers to our address**, not that its bytes
match ``eth_account``'s. They cannot match: ``eth_account`` derives k deterministically
(RFC 6979) while KMS uses a random k, so r and s differ on every call by design.
"""

from typing import Protocol

from loguru import logger

# secp256k1 group order. EIP-2 rejects signatures with s > N/2 ("malleable"): for every
# valid (r, s) the pair (r, N-s) is equally valid, so Ethereum accepts only the low one.
# KMS does not know that rule and returns whichever it computes, so we normalise.
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


class SignerError(RuntimeError):
    """Raised when a signer cannot be built or a signature cannot be assembled."""


class Signer(Protocol):
    """Signs Ethereum transactions on behalf of the coordinator EOA."""

    @property
    def address(self) -> str:
        """Checksummed address of the signing key."""
        ...

    async def sign_transaction(self, tx: dict) -> bytes:
        """Return the raw RLP-encoded signed transaction, ready for eth_sendRawTransaction."""
        ...


def _address_from_der_public_key(der: bytes) -> str:
    """Derive the Ethereum address from a DER SubjectPublicKeyInfo (what KMS hands back)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from eth_utils import keccak, to_checksum_address

    try:
        key = serialization.load_der_public_key(der)
    except Exception as exc:  # noqa: BLE001 - any parse failure is a config error
        raise SignerError(f"KMS public key is not valid DER: {type(exc).__name__}") from None
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256K1):
        raise SignerError(
            "KMS key must be an ECC_SECG_P256K1 (secp256k1) key — Ethereum uses no other curve"
        )
    # X9.62 uncompressed point: 0x04 || X (32) || Y (32). The address is the last 20 bytes
    # of keccak over X||Y, i.e. the point without its 0x04 prefix.
    point = key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return to_checksum_address(keccak(point[1:])[-20:])


def _rs_from_der_signature(der: bytes) -> tuple[int, int]:
    """Parse KMS's DER ECDSA signature into (r, s), normalised to EIP-2's low-s form."""
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    try:
        r, s = decode_dss_signature(der)
    except Exception as exc:  # noqa: BLE001 - any parse failure means we cannot sign
        raise SignerError(f"KMS signature is not valid DER: {type(exc).__name__}") from None
    if s > _SECP256K1_N // 2:
        s = _SECP256K1_N - s
    return r, s


def _recovery_id(digest: bytes, r: int, s: int, address: str) -> int:
    """Find which of the two candidate public keys for (r, s) is ours.

    ECDSA signatures do not carry the signer's identity: (r, s) is satisfied by two points
    on the curve. Ethereum stores the disambiguating bit (``v``/``y_parity``), but KMS
    never computes it — it does not know or care which key you will claim to be. So we
    recover both candidates and keep the one matching our own address.
    """
    from eth_keys import KeyAPI
    from eth_keys.exceptions import BadSignature

    keys = KeyAPI()
    for v in (0, 1):
        try:
            pub = keys.Signature(vrs=(v, r, s)).recover_public_key_from_msg_hash(digest)
        except BadSignature:
            continue
        if pub.to_checksum_address() == address:
            return v
    raise SignerError(
        "no recovery id reproduces the signer address — the KMS key does not match the "
        "address this coordinator is configured with"
    )


class LocalKeySigner:
    """Signs with an in-process private key. Dev and tests only — see module docstring."""

    def __init__(self, private_key: str) -> None:
        from eth_account import Account

        self._acct = Account.from_key(private_key)

    @property
    def address(self) -> str:
        return self._acct.address

    async def sign_transaction(self, tx: dict) -> bytes:
        signed = self._acct.sign_transaction(tx)
        return getattr(signed, "raw_transaction", None) or signed.rawTransaction


class KmsSigner:
    """Signs via AWS KMS. The private key never exists in this process.

    ``address`` is resolved once at construction (via :meth:`create`) so the hot path costs
    exactly one KMS ``Sign`` call per transaction and no key material is ever cached.
    """

    def __init__(self, key_id: str, address: str, region: str | None = None) -> None:
        self._key_id = key_id
        self._address = address
        self._region = region

    @classmethod
    async def create(cls, key_id: str, region: str | None = None) -> "KmsSigner":
        """Fetch the public key from KMS and derive the address it signs as."""
        session = _aioboto3_session()
        async with session.client("kms", region_name=region) as kms:
            try:
                resp = await kms.get_public_key(KeyId=key_id)
            except Exception as exc:  # noqa: BLE001 - surface as a config error, not a 500
                raise SignerError(
                    f"cannot read KMS key {key_id!r}: {type(exc).__name__}. The coordinator "
                    "needs kms:GetPublicKey and kms:Sign on it."
                ) from None
        address = _address_from_der_public_key(resp["PublicKey"])
        logger.info("coordinator signing via KMS key {} (address {})", key_id, address)
        return cls(key_id, address, region)

    @property
    def address(self) -> str:
        return self._address

    async def sign_transaction(self, tx: dict) -> bytes:
        from eth_account._utils.legacy_transactions import (
            encode_transaction,
            serializable_unsigned_transaction_from_dict,
        )

        unsigned = serializable_unsigned_transaction_from_dict(tx)
        digest = unsigned.hash()

        session = _aioboto3_session()
        async with session.client("kms", region_name=self._region) as kms:
            try:
                resp = await kms.sign(
                    KeyId=self._key_id,
                    Message=digest,
                    # The payload IS the hash: KMS must sign it as-is, not hash it again.
                    MessageType="DIGEST",
                    SigningAlgorithm="ECDSA_SHA_256",
                )
            except Exception as exc:  # noqa: BLE001 - never leak KMS internals to a caller
                raise SignerError(f"KMS refused to sign: {type(exc).__name__}") from None

        r, s = _rs_from_der_signature(resp["Signature"])
        v = _recovery_id(digest, r, s, self._address)
        return encode_transaction(unsigned, vrs=(v, r, s))


def _aioboto3_session():
    try:
        import aioboto3
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without extra
        raise SignerError(
            "aioboto3 is required for KMS signing; install with '.[s3]' or '.[chain]'"
        ) from exc
    return aioboto3.Session()
