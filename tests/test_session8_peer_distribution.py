"""Session 8.7 — peer-assisted distribution interface (default off, tested either way)."""

import uuid

import pytest
from app.config import get_settings
from app.peer_distribution import plan_fetch, seeders_for
from conftest import auth, make_provider
from httpx import AsyncClient

DIGEST = "f" * 64


@pytest.fixture
def _peer_flag():
    """Toggle the feature flag around a test, restoring it afterward."""
    settings = get_settings()
    original = settings.peer_distribution_enabled

    def _set(value: bool) -> None:
        settings.peer_distribution_enabled = value

    yield _set
    settings.peer_distribution_enabled = original


async def _seed(client: AsyncClient, name: str) -> uuid.UUID:
    pid, key = await make_provider(client, name, cpu_cores=8, memory_mb=16000)
    await client.post("/agent/cache", headers=auth(key), json={"cached": [DIGEST]})
    return uuid.UUID(pid)


async def test_plan_fetch_disabled_is_always_origin(client: AsyncClient, session, _peer_flag):
    seeder = await _seed(client, "seeder")
    _peer_flag(False)
    plan = await plan_fetch(session, uuid.uuid4(), DIGEST, get_settings())
    assert plan.kind == "origin" and plan.provider_id is None
    # A seeder exists but the disabled feature ignores it.
    assert await seeders_for(session, DIGEST) == [seeder]


async def test_plan_fetch_enabled_prefers_peer(client: AsyncClient, session, _peer_flag):
    seeder = await _seed(client, "seeder")
    _peer_flag(True)
    plan = await plan_fetch(session, uuid.uuid4(), DIGEST, get_settings())
    assert plan.kind == "peer" and plan.provider_id == seeder


async def test_plan_fetch_enabled_falls_back_to_origin(client: AsyncClient, session, _peer_flag):
    _peer_flag(True)
    plan = await plan_fetch(session, uuid.uuid4(), DIGEST, get_settings())
    assert plan.kind == "origin"  # no seeder


async def test_seeders_excludes_requester(client: AsyncClient, session):
    seeder = await _seed(client, "seeder")
    assert await seeders_for(session, DIGEST, exclude=seeder) == []
    assert await seeders_for(session, DIGEST) == [seeder]


async def test_peers_endpoint_respects_flag(client: AsyncClient, _peer_flag):
    await _seed(client, "seeder")
    _pid, key = await make_provider(client, "asker", cpu_cores=8, memory_mb=16000)

    _peer_flag(False)
    off = (await client.get(f"/agent/artifacts/{DIGEST}/peers", headers=auth(key))).json()
    assert off["enabled"] is False and off["kind"] == "origin" and off["seeders"] == []

    _peer_flag(True)
    on = (await client.get(f"/agent/artifacts/{DIGEST}/peers", headers=auth(key))).json()
    assert on["enabled"] is True and on["kind"] == "peer" and len(on["seeders"]) == 1
