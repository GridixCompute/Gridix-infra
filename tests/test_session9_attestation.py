"""Session 9.5 — remote attestation gates key release for confidential-tee jobs."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.attestation import sign_measurement, verify_attestation
from app.config import get_settings
from app.crypto import generate_data_key, wrap_key
from app.models import Provider
from conftest import auth, make_provider, register
from httpx import AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


def _valid_quote() -> dict:
    secret = get_settings().attestation_secret
    return {"measurement": "enclave-v1", "signature": sign_measurement("enclave-v1", secret)}


# ── verifier unit ───────────────────────────────────────────────────────────────
def test_verify_attestation_accepts_valid_rejects_tampered() -> None:
    s = get_settings()
    assert verify_attestation(_valid_quote(), s) is True
    assert verify_attestation({"measurement": "enclave-v1", "signature": "bad"}, s) is False
    assert verify_attestation({}, s) is False


# ── attestation gates key release ───────────────────────────────────────────────
async def _confidential_job_assigned(client, session, settings):
    pid, prov_key = await make_provider(client, "enclave", cpu_cores=8, memory_mb=16000)
    # Attest first, so the TEE-only scheduler will place the job here.
    await client.post("/agent/attest", headers=auth(prov_key), json=_valid_quote())

    _dev, dev_key = await register(client, "developer", "acme")
    dek = generate_data_key()
    wrapped = wrap_key(dek, settings.kek).decode()
    r = await client.post(
        "/jobs",
        headers=auth(dev_key),
        json={"image_ref": "img", "data_tier": "confidential_tee", "wrapped_key": wrapped},
    )
    job_id = uuid.UUID(r.json()["id"])
    await assign_job(session, job_id, settings)
    return job_id, prov_key, dek


async def test_valid_attestation_allows_key(client: AsyncClient, session, settings) -> None:
    job_id, prov_key, dek = await _confidential_job_assigned(client, session, settings)
    resp = await client.get(f"/agent/jobs/{job_id}/key", headers=auth(prov_key))
    assert resp.status_code == 200 and resp.json()["data_key"] == dek


async def test_tampered_attestation_is_rejected(client: AsyncClient) -> None:
    _pid, prov_key = await make_provider(client, "enclave", cpu_cores=8, memory_mb=16000)
    resp = await client.post(
        "/agent/attest",
        headers=auth(prov_key),
        json={"measurement": "enclave-v1", "signature": "forged"},
    )
    assert resp.status_code == 400
    # And without attestation the provider is not TEE-attested.
    me = await client.get("/providers/me", headers=auth(prov_key))
    assert me.status_code == 200


async def test_key_blocked_when_attestation_revoked(client: AsyncClient, session, settings) -> None:
    """If the TEE flag is cleared, the confidential job's key is no longer released."""
    job_id, prov_key, _dek = await _confidential_job_assigned(client, session, settings)
    # Revoke attestation (e.g. a later probe failed).
    provider = await session.scalar(select(Provider).where(Provider.name == "enclave"))
    provider.tee_attested = False
    await session.commit()

    resp = await client.get(f"/agent/jobs/{job_id}/key", headers=auth(prov_key))
    assert resp.status_code == 409
