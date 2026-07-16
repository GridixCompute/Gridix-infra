"""A node's reply is hostile input: it must never crash the coordinator.

The node is a counterparty that is paid from the numbers in this reply, and it chooses
every byte of it. Before this, `usage: "x"` reached `.get()` (AttributeError) and
`completion_tokens: -5` reached ChatUsage's ge=0 (ValidationError) — both unhandled, both
500. Any registered node could have broken every request routed to it, for free, and the
failure would have looked like ours.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from conftest import auth, register
from httpx import AsyncClient

from tests.test_inference import fund, make_node

pytestmark = pytest.mark.anyio


async def _setup(client: AsyncClient, session, *, models=("llama-3.1-8b",)):
    dev_id, key = await register(client, "developer", "Acme")
    await fund(session, uuid.UUID(dev_id), "10")
    await make_node(session, models=models)
    return uuid.UUID(dev_id), key


def _wrap(payload: dict) -> dict:
    """The envelope dispatch really returns. Without it the payload never reaches the
    parser and every test below passes while proving nothing."""
    return {"status": 200, "payload": payload}


async def _chat(client: AsyncClient, key: str, payload):
    with patch("app.dispatch.call_provider", new=AsyncMock(return_value=_wrap(payload))):
        return await client.post(
            "/v1/chat/completions",
            headers=auth(key),
            json={"model": "llama-3.1-8b", "messages": [{"role": "user", "content": "hi there"}]},
        )


async def test_a_well_formed_reply_still_works(client: AsyncClient, session):
    """The control. Without this, every assertion below could pass on a reply that never
    arrived — which is exactly what happened while writing them."""
    dev, key = await _setup(client, session)
    res = await _chat(
        client, key, {"content": "hi", "usage": {"prompt_tokens": 2, "completion_tokens": 5}}
    )
    assert res.status_code == 200, res.text
    assert res.json()["usage"]["completion_tokens"] == 5


class TestAMaliciousNodeCannotCrashTheCoordinator:
    """Every one of these must be a controlled failure, never a 500."""

    async def test_negative_completion_tokens(self, client: AsyncClient, session):
        dev, key = await _setup(client, session)
        res = await _chat(client, key, {"content": "x", "usage": {"completion_tokens": -5}})
        assert res.status_code != 500, "a node returning -5 tokens 500s the coordinator"

    async def test_completion_tokens_as_a_string(self, client: AsyncClient, session):
        dev, key = await _setup(client, session)
        res = await _chat(client, key, {"content": "x", "usage": {"completion_tokens": "abc"}})
        assert res.status_code != 500, "a node returning a non-numeric token count 500s"

    async def test_completion_tokens_as_a_list(self, client: AsyncClient, session):
        dev, key = await _setup(client, session)
        res = await _chat(client, key, {"content": "x", "usage": {"completion_tokens": [1, 2]}})
        assert res.status_code != 500, "a node returning a list as its token count 500s"

    async def test_usage_is_not_a_dict(self, client: AsyncClient, session):
        dev, key = await _setup(client, session)
        res = await _chat(client, key, {"content": "x", "usage": "not-a-dict"})
        assert res.status_code != 500, "a node returning a string for `usage` 500s"

    async def test_prompt_tokens_negative(self, client: AsyncClient, session):
        dev, key = await _setup(client, session)
        res = await _chat(client, key, {"content": "x", "usage": {"prompt_tokens": -99}})
        assert res.status_code != 500, "a node returning -99 prompt tokens 500s"
