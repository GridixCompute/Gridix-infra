"""Session 12.1 — secret management: KMS seam + zero-downtime KEK rotation."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.config import Settings, get_settings
from app.crypto import DecryptionError, decrypt_rotating, generate_data_key, wrap_key
from app.secret_manager import EnvSecretManager
from conftest import auth, make_provider, register
from cryptography.fernet import Fernet

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


def test_env_secret_manager_reads_by_name(monkeypatch) -> None:
    monkeypatch.setenv("GRIDIX_MY_SECRET", "value")
    assert EnvSecretManager().get("MY_SECRET") == "value"
    assert EnvSecretManager().get("MISSING") is None


def test_all_keks_orders_primary_then_retired() -> None:
    s = Settings(kek="new", kek_previous="old1, old2")
    assert s.all_keks == ["new", "old1", "old2"]


def test_rotating_decrypt_accepts_old_and_new() -> None:
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()
    token = Fernet(old.encode()).encrypt(b"data")  # encrypted under the old key
    # After rotation (new primary, old retired) it still decrypts.
    assert decrypt_rotating(token, [new, old]) == b"data"
    with pytest.raises(DecryptionError):
        decrypt_rotating(token, [new])  # old key fully retired → fails


async def test_key_release_survives_rotation(client, session, settings) -> None:
    """A DEK wrapped under the old KEK is still released after the KEK rotates."""
    old_kek = settings.kek
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "acme")
    dek = generate_data_key()
    wrapped = wrap_key(dek, old_kek).decode()  # wrapped under the CURRENT key
    r = await client.post(
        "/jobs",
        headers=auth(dev_key),
        json={"image_ref": "img", "data_tier": "encrypted_at_rest", "wrapped_key": wrapped},
    )
    job_id = uuid.UUID(r.json()["id"])
    await assign_job(session, job_id, settings)

    # Rotate: a new primary KEK, old one retired but still accepted.
    new_kek = Fernet.generate_key().decode()
    s = get_settings()
    s.kek, s.kek_previous = new_kek, old_kek
    try:
        resp = await client.get(f"/agent/jobs/{job_id}/key", headers=auth(prov_key))
        assert resp.status_code == 200 and resp.json()["data_key"] == dek
    finally:
        s.kek, s.kek_previous = old_kek, ""
