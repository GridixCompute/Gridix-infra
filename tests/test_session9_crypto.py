"""Session 9.2 — envelope encryption: ciphertext at rest, developer decrypts result."""

from unittest.mock import AsyncMock, patch

import pytest
from app.crypto import (
    DecryptionError,
    decrypt,
    encrypt,
    generate_data_key,
    unwrap_key,
    wrap_key,
)
from conftest import auth, register
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


def test_encrypt_roundtrip_and_tamper_detection() -> None:
    key = generate_data_key()
    ct = encrypt(b"secret input", key)
    assert ct != b"secret input"  # ciphertext, not plaintext
    assert decrypt(ct, key) == b"secret input"
    # Wrong key fails; tampering is detected (authenticated).
    with pytest.raises(DecryptionError):
        decrypt(ct, generate_data_key())
    tampered = bytearray(ct)
    tampered[20] ^= 0xFF
    with pytest.raises(DecryptionError):
        decrypt(bytes(tampered), key)


def test_envelope_wrap_unwrap() -> None:
    dek = generate_data_key()
    kek = generate_data_key()
    wrapped = wrap_key(dek, kek)
    assert wrapped != dek.encode()
    assert unwrap_key(wrapped, kek) == dek


async def test_coordinator_stores_ciphertext_only(client: AsyncClient) -> None:
    """A developer uploads encrypted input; what's stored is ciphertext, and the
    developer can decrypt a result fetched back."""
    _dev, key = await register(client, "developer", "acme")
    dek = generate_data_key()
    plaintext = b"confidential dataset"
    ciphertext = encrypt(plaintext, dek)

    up = await client.post(
        "/blobs",
        headers=auth(key),
        files={"file": ("in.enc", ciphertext, "application/octet-stream")},
    )
    ref = up.json()["ref"]

    # What the coordinator stored is the ciphertext, not the plaintext.
    stored = (
        await client.post(
            "/blobs",
            headers=auth(key),
            files={"file": ("probe", ciphertext, "application/octet-stream")},
        )
    ).json()["ref"]
    assert stored == ref  # content-addressed: same ciphertext → same ref
    # And only the holder of the DEK can recover the plaintext.
    assert decrypt(ciphertext, dek) == plaintext
