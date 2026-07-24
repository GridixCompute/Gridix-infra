"""The /v1 responses must be shaped the way OpenAI shapes them.

The endpoints live at OpenAI paths and take OpenAI requests, so a developer will point an
OpenAI SDK at them — that is the whole promise of "change the base_url". The previous
shape (``{model, content, usage, ...}``) was close enough to invite that and wrong enough
to break on the first read of ``choices``, which fails *after* the integration is written.

These tests pin the envelope field by field rather than round-tripping through a client
library, so a break names the field that moved instead of surfacing as a parse error from
inside somebody else's package.
"""

import base64
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from conftest import auth, register
from httpx import AsyncClient
from test_inference import CHAT_MODEL, IMAGE_MODEL, fund, make_node, node_reply


@pytest.fixture(autouse=True)
def _clean_inflight():
    from app.dispatch import reset_inflight

    reset_inflight()
    yield
    reset_inflight()


async def _chat(client: AsyncClient, session, *, reply=None, **over):
    dev_id, key = await register(client, "developer", "Acme")
    await fund(session, uuid.UUID(dev_id), "10")
    await make_node(session)
    body = {"model": CHAT_MODEL, "messages": [{"role": "user", "content": "hi"}], **over}
    with patch("app.dispatch.call_provider", new=AsyncMock(return_value=reply or node_reply())):
        return await client.post("/v1/chat/completions", headers=auth(key), json=body)


class TestChatEnvelope:
    async def test_it_carries_every_field_an_openai_client_reads(
        self, client: AsyncClient, session
    ) -> None:
        res = await _chat(client, session)
        assert res.status_code == 200, res.text
        body = res.json()

        assert body["object"] == "chat.completion"
        assert body["id"].startswith("chatcmpl-")
        assert isinstance(body["created"], int) and body["created"] > 0
        assert body["model"] == CHAT_MODEL

        choice = body["choices"][0]
        assert choice["index"] == 0
        assert choice["message"] == {"role": "assistant", "content": "hello"}
        assert choice["finish_reason"] in ("stop", "length")

    async def test_usage_reports_total_tokens_on_the_wire(
        self, client: AsyncClient, session
    ) -> None:
        """It was a @property before, so it existed in Python and not in the JSON — a
        client reading usage.total_tokens got nothing."""
        res = await _chat(client, session, reply=node_reply(prompt=10, completion=100))
        usage = res.json()["usage"]
        assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
        assert usage["total_tokens"] == 110

    async def test_every_response_has_its_own_id(self, client: AsyncClient, session) -> None:
        first = (await _chat(client, session)).json()["id"]
        second = (await _chat(client, session)).json()["id"]
        assert first != second

    async def test_finish_reason_is_length_when_the_node_used_its_whole_budget(
        self, client: AsyncClient, session
    ) -> None:
        res = await _chat(
            client,
            session,
            max_tokens=64,
            reply=node_reply(prompt=10, completion=64),
        )
        assert res.json()["choices"][0]["finish_reason"] == "length"

    async def test_finish_reason_is_stop_when_it_ended_on_its_own(
        self, client: AsyncClient, session
    ) -> None:
        res = await _chat(
            client, session, max_tokens=64, reply=node_reply(prompt=10, completion=12)
        )
        assert res.json()["choices"][0]["finish_reason"] == "stop"

    async def test_the_gridix_extras_survive_the_reshape(
        self, client: AsyncClient, session
    ) -> None:
        """Conformance was not bought by throwing away what the network knows: an OpenAI
        client ignores unknown fields, so these cost nothing and answer "what did this
        cost, who served it" without a second request."""
        body = (await _chat(client, session)).json()
        assert Decimal(body["cost_usdc"]) > 0
        uuid.UUID(body["provider_id"])  # raises if it is not a provider id


class TestImageEnvelope:
    async def test_it_is_the_openai_images_envelope(self, client: AsyncClient, session) -> None:
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session, models=(IMAGE_MODEL,))

        img_a = base64.b64encode(b"\x89PNG\r\n-a-").decode("ascii")
        img_b = base64.b64encode(b"\x89PNG\r\n-b-").decode("ascii")
        reply = {"status": 200, "payload": {"images": [img_a, img_b]}}
        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=reply)):
            res = await client.post(
                "/v1/images/generations",
                headers=auth(key),
                json={"model": IMAGE_MODEL, "prompt": "a cat", "n": 2},
            )

        assert res.status_code == 200, res.text
        body = res.json()
        assert isinstance(body["created"], int) and body["created"] > 0
        # OpenAI's images envelope: data[].url. The URLs are coordinator-stored and reachable.
        assert len(body["data"]) == 2
        assert all(set(item) == {"url"} for item in body["data"])
        assert all("/public/image/" in item["url"] for item in body["data"])
        # Extras, same as chat.
        assert body["model"] == IMAGE_MODEL
        assert Decimal(body["cost_usdc"]) > 0


class TestTheContractIsPublished:
    async def test_the_openapi_schema_describes_the_openai_shape(self) -> None:
        """A generated client is built from the schema, not from a live response — so the
        schema has to carry the envelope too, or typed clients go wrong while the runtime
        is right."""
        from app.main import app

        schemas = app.openapi()["components"]["schemas"]

        chat = schemas["ChatCompletionResponse"]["properties"]
        assert set(chat) >= {"id", "object", "created", "model", "choices", "usage"}
        assert set(chat) >= {"cost_usdc", "provider_id"}, "the Gridix extras must stay public"

        assert "total_tokens" in schemas["ChatUsage"]["properties"]

        choice = schemas["ChatChoice"]["properties"]
        assert set(choice) >= {"index", "message", "finish_reason"}

        image = schemas["ImageGenerationResponse"]["properties"]
        assert set(image) >= {"created", "data"}
