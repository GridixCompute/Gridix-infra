"""A node is paid per image it returns, so "an image" must mean an image.

`[str(u) for u in reply.get("images")]` iterates whatever it is handed, and strings are
iterable — so a node returning the string "abc" produced three "images" and was billed as
having done three pictures' work. Three bytes for three images' pay.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.usage_billing import developer_balance
from conftest import auth, register
from httpx import AsyncClient
from test_inference import fund, make_node

pytestmark = pytest.mark.anyio

IMAGE_MODEL = "sdxl-turbo"


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

    res = await _generate(client, key, {"images": ["u1", "u2", "u3"]})
    assert res.status_code == 200, res.text
    assert res.json()["images"] == ["u1", "u2", "u3"]

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
    assert res.json()["images"] == [], f"{images!r} was turned into {res.json()['images']}"

    session.expire_all()
    charged = before - await developer_balance(session, dev)
    assert charged == 0, f"node returned {images!r} — no images — and was paid {charged}"
