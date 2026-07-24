"""The free image path end to end: wallet-gated, quota'd, dispatched, stored, served.

A mock node returns the image BY VALUE (base64). The proof this file exists for is the
production trap it closes: the coordinator must store those bytes and hand back a reachable,
non-pod-local URL — never the node's own ``http://127.0.0.1:8500/...``, which a browser cannot
reach and which dies with the node. The wallet gate, prompt filter, and per-wallet daily quota
are unchanged from the old 503 stub; these tests prove they still hold around a real dispatch.
"""

import base64
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.dispatch import reset_inflight
from app.free_tier import FREE_IMAGE_MODEL
from app.ledger import deposit_stake
from app.models import Provider, ProviderModel
from conftest import auth, wallet_address, wallet_sign_in
from httpx import AsyncClient

# A distinct, valid-base64 payload. The store path does not parse PNG, so any bytes round-trip.
IMAGE_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n-a-generated-image-\x00\x01").decode("ascii")


@pytest.fixture(autouse=True)
def _reset_inflight():
    yield
    reset_inflight()


async def make_image_node(session) -> Provider:
    """A staked, connected node advertising the free image model."""
    now = datetime.now(UTC)
    provider = Provider(
        name=f"img-{uuid.uuid4().hex[:6]}",
        last_seen=now,
        connected_at=now,
        wallet_address=wallet_address(),
    )
    session.add(provider)
    await session.flush()
    session.add(ProviderModel(provider_id=provider.id, model=FREE_IMAGE_MODEL))
    await deposit_stake(session, provider.id, Decimal(1000))
    await session.commit()
    return provider


async def test_free_image_end_to_end_stores_and_serves_a_reachable_url(
    client: AsyncClient, session
) -> None:
    await make_image_node(session)
    _, session_key = await wallet_sign_in(client)
    headers = auth(session_key)

    before = (await client.get("/public/images/quota", headers=headers)).json()
    assert before["remaining"] == 5

    with patch("app.routes.public.dispatch", new=AsyncMock(return_value={"images": [IMAGE_B64]})):
        res = await client.post(
            "/public/images", headers=headers, json={"prompt": "a red bicycle on a beach"}
        )

    assert res.status_code == 200, res.text
    body = res.json()
    url = body["data"][0]["url"]
    # The trap the PR fixes: a reachable coordinator URL, never the node's pod-local address.
    assert "/public/image/" in url
    assert "127.0.0.1:8500" not in url
    assert body["model"] == FREE_IMAGE_MODEL

    after = (await client.get("/public/images/quota", headers=headers)).json()
    assert after["remaining"] == 4, "the wallet quota did not decrement"

    # The URL actually serves the stored bytes — content-addressed, so it outlives the node.
    ref = url.rsplit("/", 1)[-1]
    served = await client.get(f"/public/image/{ref}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == base64.b64decode(IMAGE_B64)


async def test_no_node_serving_images_is_503(client: AsyncClient) -> None:
    _, session_key = await wallet_sign_in(client)
    res = await client.post("/public/images", headers=auth(session_key), json={"prompt": "a cat"})
    assert res.status_code == 503
    assert "node" in res.text.lower()


async def test_a_refused_prompt_neither_dispatches_nor_spends_quota(
    client: AsyncClient, session
) -> None:
    await make_image_node(session)
    _, session_key = await wallet_sign_in(client)
    headers = auth(session_key)

    call = AsyncMock()
    with patch("app.routes.public.dispatch", new=call):
        res = await client.post("/public/images", headers=headers, json={"prompt": "nude child"})

    assert res.status_code == 400
    call.assert_not_awaited()  # screening refuses BEFORE a node is touched
    assert (await client.get("/public/images/quota", headers=headers)).json()["remaining"] == 5


async def test_a_node_returning_no_image_is_502_not_a_broken_200(
    client: AsyncClient, session
) -> None:
    await make_image_node(session)
    _, session_key = await wallet_sign_in(client)
    with patch("app.routes.public.dispatch", new=AsyncMock(return_value={"images": []})):
        res = await client.post(
            "/public/images", headers=auth(session_key), json={"prompt": "a cat"}
        )
    assert res.status_code == 502


async def test_the_download_route_404s_an_unknown_ref(client: AsyncClient) -> None:
    res = await client.get("/public/image/" + "0" * 64 + ".png")
    assert res.status_code == 404


async def test_image_generation_still_requires_a_wallet_session(client: AsyncClient) -> None:
    """The gate is unchanged: no anonymous image generation, even now that it really works."""
    assert (await client.post("/public/images", json={"prompt": "a cat"})).status_code == 401
