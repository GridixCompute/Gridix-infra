"""Session 1 — foundation: health probe and API-key auth.

Registration itself is no longer here: developers come to exist through SIWE sign-in
(``tests/test_wallet_auth.py``) and providers through ``/providers/onboard``
(``tests/test_provider_wallet_auth.py``). What remains foundational is that the minted
keys authenticate the right principal and are not interchangeable across roles.
"""

from unittest.mock import AsyncMock, patch

import pytest
from app.main import create_app
from conftest import auth, register
from httpx import ASGITransport, AsyncClient


async def test_health_degraded_when_redis_down(client: AsyncClient) -> None:
    """DB reachable but Redis down → 503 with database=True, redis=False."""
    resp = await client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["database"] is True
    assert body["redis"] is False
    assert body["status"] == "degraded"


async def test_health_ok_when_both_up(client: AsyncClient) -> None:
    """Both dependencies reachable → 200 ok."""
    with patch("app.routes.health.get_redis") as get_redis:
        get_redis.return_value.ping = AsyncMock(return_value=True)
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": True, "redis": True}


async def test_a_developer_wallet_session_yields_a_working_key(client: AsyncClient) -> None:
    """A signed-in developer gets a programmatic key that works on a developer route."""
    _id, key = await register(client, "developer", "Acme")
    assert key.startswith("grdx_")
    assert (await client.get("/jobs", headers=auth(key))).status_code == 200


async def test_onboarding_a_provider_yields_a_working_key(client: AsyncClient) -> None:
    """Onboarding a provider yields an id and a one-time node agent key."""
    _id, key = await register(client, "provider", "GPU-Farm")
    assert key.startswith("grdx_")


async def _probe_client() -> AsyncClient:
    """Build a client whose app has developer/provider-only probe routes mounted."""
    from app.deps import DeveloperDep, ProviderDep

    app = create_app()

    @app.get("/_dev_only")
    async def _dev_only(dev: DeveloperDep) -> dict[str, str]:
        return {"id": str(dev.id)}

    @app.get("/_prov_only")
    async def _prov_only(prov: ProviderDep) -> dict[str, str]:
        return {"id": str(prov.id)}

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_developer_and_provider_keys_are_not_interchangeable() -> None:
    """A developer key is accepted on a developer route and 403'd on a provider route."""
    async with await _probe_client() as c:
        dev_id, dev_key = await register(c, "developer", "Acme")
        prov_id, prov_key = await register(c, "provider", "Farm")

        assert (await c.get("/_dev_only", headers=auth(dev_key))).status_code == 200
        assert (await c.get("/_prov_only", headers=auth(prov_key))).status_code == 200
        # Cross-use is forbidden.
        assert (await c.get("/_prov_only", headers=auth(dev_key))).status_code == 403
        assert (await c.get("/_dev_only", headers=auth(prov_key))).status_code == 403


@pytest.mark.parametrize("header", [None, "Bearer", "Token abc", "Bearer grdx_wrong"])
async def test_missing_or_invalid_auth_is_unauthorized(header: str | None) -> None:
    """Absent, malformed, or unknown keys are rejected with 401 on a protected route."""
    async with await _probe_client() as c:
        headers = {"Authorization": header} if header is not None else {}
        resp = await c.get("/_dev_only", headers=headers)
        assert resp.status_code == 401
