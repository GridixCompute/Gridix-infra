"""Session 9.1 — data-handling policy tiers on jobs."""

from unittest.mock import AsyncMock, patch

import pytest
from conftest import auth, register
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


async def test_default_tier_is_public(client: AsyncClient) -> None:
    _dev, key = await register(client, "developer", "acme")
    r = await client.post("/jobs", headers=auth(key), json={"image_ref": "img"})
    assert r.json()["data_tier"] == "public"


@pytest.mark.parametrize("tier", ["public", "encrypted_at_rest", "confidential_tee"])
async def test_valid_tiers_accepted(client: AsyncClient, tier: str) -> None:
    _dev, key = await register(client, "developer", "acme")
    r = await client.post("/jobs", headers=auth(key), json={"image_ref": "img", "data_tier": tier})
    assert r.status_code == 201
    assert r.json()["data_tier"] == tier


async def test_invalid_tier_rejected(client: AsyncClient) -> None:
    _dev, key = await register(client, "developer", "acme")
    r = await client.post(
        "/jobs", headers=auth(key), json={"image_ref": "img", "data_tier": "top_secret"}
    )
    assert r.status_code == 422
