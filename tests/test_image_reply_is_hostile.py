"""A node is paid per image it returns, so "an image" must mean an image.

The store step (``app.image_artifacts.store_node_images``) iterates ``reply["images"]``, and
strings are iterable — so a node returning the string ``"abc"`` could have produced three
"images" and been billed for three pictures' work. The guard: anything that is not a *list* is
treated as no images, and each list element must be a valid base64 image or it is skipped. A
malformed reply is billed nothing, never garbage.
"""

import base64
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.usage_billing import developer_balance
from conftest import auth, register
from httpx import AsyncClient
from test_inference import fund, make_node

pytestmark = pytest.mark.anyio

IMAGE_MODEL = "sdxl-turbo"


def _b64(tag: bytes) -> str:
    return base64.b64encode(b"\x89PNG\r\n" + tag).decode("ascii")


async def _setup(client: AsyncClient, session):
    dev_id, key = await register(client, "developer", "Acme")
    await fund(session, uuid.UUID(dev_id), "10")
    await make_node(session, models=(IMAGE_MODEL,))
    return uuid.UUID(dev_id), key


async def _generate(client: AsyncClient, key: str, payload, n=3):
    reply = {"status": 200, "payload": payload}
    with patch("app.dispatch.call_provider", new=AsyncMock(return_value=reply)):
        return await client.post(
            "/v1/images/generations",
            headers=auth(key),
            json={"model": IMAGE_MODEL, "prompt": "a globe", "n": n},
        )


async def test_real_images_are_still_billed(client: AsyncClient, session):
    """The control: without it, every assertion below passes if the route bills nothing."""
    dev, key = await _setup(client, session)
    before = await developer_balance(session, dev)

    res = await _generate(client, key, {"images": [_b64(b"a"), _b64(b"b"), _b64(b"c")]})
    assert res.status_code == 200, res.text
    # Three real images back → three reachable, coordinator-stored URLs (not the node's own).
    urls = [i["url"] for i in res.json()["data"]]
    assert len(urls) == 3
    assert all("/public/image/" in u for u in urls)

    session.expire_all()
    assert before - await developer_balance(session, dev) > 0, "a real generation was free"


@pytest.mark.parametrize(
    "images",
    [
        pytest.param("abc", id="a-string-iterates-into-characters"),
        pytest.param({"a": 1}, id="a-dict-iterates-into-keys"),
        pytest.param(7, id="a-number"),
    ],
)
async def test_a_reply_that_is_not_a_list_of_images_pays_nothing(
    client: AsyncClient, session, images
):
    dev, key = await _setup(client, session)
    before = await developer_balance(session, dev)

    res = await _generate(client, key, {"images": images})
    assert res.status_code == 200, res.text
    assert res.json()["data"] == [], f"{images!r} was turned into {res.json()['data']}"

    session.expire_all()
    charged = before - await developer_balance(session, dev)
    assert charged == 0, f"node returned {images!r} — no images — and was paid {charged}"


async def test_list_of_non_base64_junk_pays_nothing(client: AsyncClient, session):
    """A list, but of things that are not images: each element fails to decode and is skipped."""
    dev, key = await _setup(client, session)
    before = await developer_balance(session, dev)

    # 2-char strings are not valid base64 (length not a multiple of 4) → all skipped.
    res = await _generate(client, key, {"images": ["u1", "u2", "u3"]})
    assert res.status_code == 200, res.text
    assert res.json()["data"] == []

    session.expire_all()
    assert before - await developer_balance(session, dev) == 0, "junk strings were paid for"
