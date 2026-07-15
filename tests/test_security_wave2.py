"""Security wave 2 — rate-limit fails CLOSED, and the endpoint gateway can't be
coerced toward internal hosts. Each test exercises the attack and asserts it fails.
"""

import uuid
from unittest.mock import patch

import app.ratelimit as ratelimit
import pytest
from app.config import get_settings
from app.models import Job, JobKind, JobStatus
from app.routes.endpoints import _safe_forward_path
from app.security import endpoint_token
from conftest import register
from fastapi import HTTPException
from httpx import AsyncClient


# ── 2.3 Rate limit fails CLOSED when Redis is down ───────────────────────────────
@pytest.fixture(autouse=True)
def _clear_local_windows():
    ratelimit._local_windows.clear()
    yield
    ratelimit._local_windows.clear()


async def test_rate_limit_stays_enforced_when_redis_is_down() -> None:
    """With Redis unreachable a flood must still be capped — NOT allowed through.

    The old code returned True (fail-open) on any Redis error, so an attacker could
    flood until Redis tipped over and the limit vanished. Now it falls back to a local
    counter that keeps enforcing.
    """

    def _boom():
        raise ConnectionError("redis down")

    with patch.object(ratelimit, "get_redis", _boom):
        results = [await ratelimit.check_rate_limit("attacker", limit=3) for _ in range(10)]

    # Fail-closed: the first few pass, the rest are blocked — never all-allowed.
    assert results[:3] == [True, True, True]
    assert all(r is False for r in results[3:])
    assert results.count(True) == 3


async def test_rate_limit_local_fallback_is_per_identity() -> None:
    """The fallback isolates identities, so one flooder can't exhaust another's budget."""

    def _boom():
        raise ConnectionError("redis down")

    with patch.object(ratelimit, "get_redis", _boom):
        for _ in range(5):
            await ratelimit.check_rate_limit("noisy", limit=3)
        # A different identity still has its full budget.
        assert await ratelimit.check_rate_limit("quiet", limit=3) is True


# ── 2.4 Endpoint gateway path can't reach internal hosts ─────────────────────────
def test_safe_forward_path_normalises_and_neutralises() -> None:
    # Ordinary paths pass through with a single leading slash.
    assert _safe_forward_path("foo/bar") == "/foo/bar"
    # Leading slashes are collapsed so it can never become protocol-relative //host.
    assert (
        _safe_forward_path("//169.254.169.254/latest/meta-data")
        == "/169.254.169.254/latest/meta-data"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "http://169.254.169.254/latest",  # embedded scheme
        "https://internal-redis:6379/",  # embedded scheme
        "user@169.254.169.254",  # userinfo host injection
        "a/../../etc/passwd",  # traversal
        "x\\y",  # backslash
        "x\x00y",  # null byte
    ],
)
def test_safe_forward_path_rejects_host_injection_and_traversal(bad: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _safe_forward_path(bad)
    assert exc.value.status_code == 400


async def test_gateway_rejects_host_injection_over_http(client: AsyncClient, session) -> None:
    """End-to-end: a valid-token request whose path injects a host is rejected (400),
    before anything is forwarded — the request that must never reach a provider fails."""
    dev_id, _ = await register(client, "developer", "dev")
    job = Job(
        developer_id=uuid.UUID(dev_id),
        kind=JobKind.standard,
        status=JobStatus.running,
        image_ref="ghcr.io/acme/server:latest",
        exposed_port=8080,
        assigned_provider_id=uuid.uuid4(),
    )
    session.add(job)
    await session.commit()

    token = endpoint_token(str(job.id), get_settings().endpoint_signing_key)
    resp = await client.get(
        f"/endpoints/{job.id}/admin@169.254.169.254",
        headers={"x-endpoint-token": token},
    )
    assert resp.status_code == 400
