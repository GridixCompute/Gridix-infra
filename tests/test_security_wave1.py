"""Security wave 1 — proof that forged auth and operator-auth bypass are closed.

Every test here demonstrates a specific attack that USED to work (or would work with a
single shared secret) and is now rejected. These are regression tests: the request that
must never succeed is exercised and asserted to fail.
"""

import pytest
from app.config import Settings, get_settings
from app.main import create_app
from app.secret_manager import SecretConfigurationError, validate_secret_config
from app.security import (
    endpoint_token,
    hash_api_key,
    verify_endpoint_token,
)
from conftest import auth, register
from httpx import ASGITransport, AsyncClient

# Four distinct per-function secrets, as a real production deployment must have.
SEP = {
    "hmac_key": "hmac-key-AAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "operator_secret": "operator-secret-BBBBBBBBBBBBBBBBBBB",
    "relay_secret": "relay-secret-CCCCCCCCCCCCCCCCCCCCCC",
    "endpoint_key": "endpoint-key-DDDDDDDDDDDDDDDDDDDDDD",
}


# ── 1.1 Secret separation: no cross-use between functions ────────────────────────
def test_api_key_hashed_under_wrong_secret_never_matches() -> None:
    """A key forged/hashed with the old or any other secret produces a different digest,
    so it can never be found in the store → the forged key is rejected at lookup."""
    plaintext = "grdx_victim_key"
    real = hash_api_key(plaintext, SEP["hmac_key"])
    for wrong in ("dev-insecure-secret-change-me", SEP["operator_secret"], SEP["endpoint_key"]):
        assert hash_api_key(plaintext, wrong) != real


def test_endpoint_token_from_wrong_secret_is_rejected() -> None:
    """An endpoint capability token signed with any non-endpoint secret fails verification —
    the endpoint signer cannot be spoofed using another function's key."""
    job = "job-123"
    good = endpoint_token(job, SEP["endpoint_key"])
    assert verify_endpoint_token(job, good, SEP["endpoint_key"]) is True
    # A token minted with the HMAC/operator/relay secret must NOT validate.
    for wrong in ("hmac_key", "operator_secret", "relay_secret"):
        forged = endpoint_token(job, SEP[wrong])
        assert verify_endpoint_token(job, forged, SEP["endpoint_key"]) is False


def test_prod_boot_rejects_a_single_missing_secret() -> None:
    """One of the four secrets left empty in production → refuse to boot, naming it."""
    settings = Settings(
        env="prod",
        kek="real-kek",
        attestation_secret="real-att",
        **{**SEP, "endpoint_key": ""},
    )
    with pytest.raises(SecretConfigurationError, match="GRIDIX_ENDPOINT_KEY"):
        validate_secret_config(settings)


def test_prod_boot_rejects_secret_reuse() -> None:
    """Reusing one value across two functions defeats separation → refuse to boot."""
    settings = Settings(
        env="prod",
        kek="real-kek",
        attestation_secret="real-att",
        **{**SEP, "relay_secret": SEP["hmac_key"]},  # relay reuses the HMAC secret
    )
    with pytest.raises(SecretConfigurationError, match="reuses"):
        validate_secret_config(settings)


def test_dev_still_boots_on_defaults() -> None:
    """Backward-compat: local dev with the baked-in default is allowed (no separation)."""
    validate_secret_config(Settings(env="dev"))


# ── 1.2 Operator-auth bypass: an API key can never reach operator endpoints ───────
@pytest.fixture
def sep_client_app():
    """An app whose settings use four DISTINCT secrets, so operator auth is truly
    separated from the API-key HMAC secret."""
    base = get_settings()
    sep_settings = base.model_copy(update=SEP)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: sep_settings
    return app, sep_settings


async def _sep_client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_provider_api_key_cannot_reach_operator_endpoint(sep_client_app) -> None:
    """A provider with a VALID API key calling an operator-only endpoint is rejected —
    there is no escalation path from 'holds an API key' to 'operator access'."""
    app, _ = sep_client_app
    async with await _sep_client(app) as client:
        _pid, provider_key = await register(client, "provider", "farm")

        # Sanity: the key IS valid for the provider's own endpoint.
        assert (await client.get("/providers/me", headers=auth(provider_key))).status_code == 200

        # ...but NOT for the operator endpoint.
        resp = await client.get("/disputes/review-queue", headers=auth(provider_key))
        assert resp.status_code in (401, 403)


async def test_hmac_secret_is_not_accepted_as_operator_credential(sep_client_app) -> None:
    """The API-key HMAC secret (which signs every developer/provider key) must NOT be
    usable as operator credentials — the exact reuse the audit flagged."""
    app, sep = sep_client_app
    async with await _sep_client(app) as client:
        # Presenting the HMAC signing secret as a bearer token → rejected.
        resp = await client.get(
            "/disputes/review-queue", headers={"Authorization": f"Bearer {SEP['hmac_key']}"}
        )
        assert resp.status_code in (401, 403)


async def test_operator_secret_is_accepted(sep_client_app) -> None:
    """The dedicated operator secret authenticates the operator endpoint."""
    app, sep = sep_client_app
    async with await _sep_client(app) as client:
        resp = await client.get(
            "/disputes/review-queue",
            headers={"Authorization": f"Bearer {SEP['operator_secret']}"},
        )
        assert resp.status_code == 200


async def test_operator_secret_is_not_a_valid_api_key(sep_client_app) -> None:
    """Cross-use the other direction: the operator secret is not a registered API key,
    so it cannot authenticate as a developer/provider."""
    app, sep = sep_client_app
    async with await _sep_client(app) as client:
        resp = await client.get(
            "/providers/me", headers={"Authorization": f"Bearer {SEP['operator_secret']}"}
        )
        assert resp.status_code == 401
