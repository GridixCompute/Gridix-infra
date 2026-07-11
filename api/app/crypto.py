"""Envelope encryption for confidential jobs (Session 9.2).

The developer encrypts a job's input under a fresh per-job *data key* (DEK) and uploads
only ciphertext; the result is encrypted back to the developer the same way. The
coordinator stores ciphertext and never sees plaintext. The DEK itself is wrapped under a
recipient's *key-encryption key* (KEK) so it can be brokered to the assigned agent
(Session 9.3) without ever transiting in the clear.

Uses Fernet (AES-128-CBC + HMAC-SHA256) — authenticated, so tampering is detected on
decrypt. Keys are urlsafe-base64 strings.
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class DecryptionError(Exception):
    """Raised when ciphertext can't be decrypted (wrong key or tampered)."""


def decrypt_rotating(ciphertext: bytes, keys: list[str]) -> bytes:
    """Decrypt with any of ``keys`` (primary first) — enables zero-downtime rotation.

    During a rotation the new key is primary and the retired key(s) still decrypt existing
    ciphertext, so nothing breaks while re-wrapping catches up.
    """
    if not keys:
        raise DecryptionError("no decryption keys configured")
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys]).decrypt(ciphertext)
    except (InvalidToken, ValueError, TypeError) as exc:
        raise DecryptionError("decryption failed (wrong key or tampered ciphertext)") from exc


def generate_data_key() -> str:
    """Return a fresh symmetric data key (DEK) as a urlsafe-base64 string."""
    return Fernet.generate_key().decode()


def encrypt(plaintext: bytes, key: str) -> bytes:
    """Encrypt ``plaintext`` under ``key`` (authenticated)."""
    return Fernet(key.encode()).encrypt(plaintext)


def decrypt(ciphertext: bytes, key: str) -> bytes:
    """Decrypt ``ciphertext`` under ``key``. Raises :class:`DecryptionError` on failure."""
    try:
        return Fernet(key.encode()).decrypt(ciphertext)
    except (InvalidToken, ValueError, TypeError) as exc:
        raise DecryptionError("decryption failed (wrong key or tampered ciphertext)") from exc


def wrap_key(dek: str, kek: str) -> bytes:
    """Wrap a data key under a key-encryption key for safe transit/storage."""
    return encrypt(dek.encode(), kek)


def unwrap_key(wrapped: bytes, kek: str) -> str:
    """Recover a wrapped data key using the key-encryption key."""
    return decrypt(wrapped, kek).decode()
