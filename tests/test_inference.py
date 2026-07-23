"""The /v1 inference path: gate, dispatch, charge.

The load-bearing claim is about money: a request that fails is never billed, and a
request that succeeds is billed on what it actually used — not on the estimate that
sized the gate. Both are mutation-tested in test_inference_guards.py.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.dispatch import reset_inflight
from app.ledger import deposit_stake
from app.models import Provider, ProviderModel
from app.usage_billing import credit_deposit, developer_balance
from conftest import auth, register, wallet_address
from httpx import AsyncClient

CHAT_MODEL = "llama-3.1-8b"
IMAGE_MODEL = "sdxl-turbo"


@pytest.fixture(autouse=True)
def _clean_inflight():
    reset_inflight()
    yield
    reset_inflight()


async def make_node(session, *, models=(CHAT_MODEL,), stake=1000, tee=False, last_seen=None):
    """A staked, connected node serving ``models``."""
    from datetime import UTC, datetime

    now = last_seen or datetime.now(UTC)
    provider = Provider(
        name=f"node-{uuid.uuid4().hex[:6]}",
        tee_attested=tee,
        last_seen=now,
        connected_at=now,
        wallet_address=wallet_address(),
    )
    session.add(provider)
    await session.flush()
    session.add_all(ProviderModel(provider_id=provider.id, model=m) for m in models)
    if stake:
        await deposit_stake(session, provider.id, Decimal(stake))
    await session.commit()
    return provider


async def fund(session, developer_id: uuid.UUID, amount: str) -> None:
    await credit_deposit(session, developer_id=developer_id, amount=Decimal(amount))
    await session.commit()


def node_reply(*, prompt=10, completion=100, content="hello"):
    return {
        "status": 200,
        "payload": {
            "content": content,
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
        },
    }


async def chat(client: AsyncClient, key: str, **over):
    body = {"model": CHAT_MODEL, "messages": [{"role": "user", "content": "hi there"}], **over}
    return await client.post("/v1/chat/completions", headers=auth(key), json=body)


class TestModels:
    async def test_lists_the_catalogue_with_prices(self, client: AsyncClient) -> None:
        _, key = await register(client, "developer", "Acme")
        res = await client.get("/v1/models", headers=auth(key))
        assert res.status_code == 200
        models = {m["id"]: m for m in res.json()["models"]}
        assert CHAT_MODEL in models and IMAGE_MODEL in models
        assert Decimal(models[CHAT_MODEL]["output_usdc_per_mtok"]) > 0

    async def test_reports_availability_rather_than_hiding_offline_models(
        self, client: AsyncClient, session
    ) -> None:
        _, key = await register(client, "developer", "Acme")
        res = await client.get("/v1/models", headers=auth(key))
        assert {m["id"]: m["available"] for m in res.json()["models"]}[CHAT_MODEL] is False

        await make_node(session)
        res = await client.get("/v1/models", headers=auth(key))
        by_id = {m["id"]: m for m in res.json()["models"]}
        assert by_id[CHAT_MODEL]["available"] is True
        assert by_id[CHAT_MODEL]["nodes"] == 1

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/v1/models")).status_code == 401


class TestChat:
    async def test_dispatches_and_returns_the_nodes_answer(
        self, client: AsyncClient, session
    ) -> None:
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        node = await make_node(session)

        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=node_reply())):
            res = await chat(client, key)

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["choices"][0]["message"]["content"] == "hello"
        assert body["provider_id"] == str(node.id)
        assert body["usage"] == {
            "prompt_tokens": 10,
            "completion_tokens": 100,
            "total_tokens": 110,
        }

    async def test_charges_actual_usage_not_the_estimate(
        self, client: AsyncClient, session
    ) -> None:
        """The bill follows the node's reported tokens. The estimate only sizes the gate.

        The numbers are chosen to be three different things: the prompt estimate is 2
        tokens, the ceiling allows 2000 output, and the node reports 500/1000. Billing
        the estimate or billing the ceiling both give a different answer than this.

        Not billing *more* than the ceiling is a separate claim, and lives with the other
        money guards in test_inference_guards.py.
        """
        dev_id, key = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        await make_node(session)

        with patch(
            "app.dispatch.call_provider",
            new=AsyncMock(return_value=node_reply(prompt=500, completion=1000)),
        ):
            res = await chat(client, key, max_tokens=2000)
        assert res.status_code == 200

        # 500 in @ 0.05/Mtok + 1000 out @ 0.08/Mtok = 0.000105 USDC exactly.
        assert Decimal(res.json()["cost_usdc"]) == Decimal("0.000105")
        session.expire_all()
        assert await developer_balance(session, dev) == Decimal("9.999895")

    def test_the_spec_declares_the_stream_it_can_return(self) -> None:
        """`stream=true` answers with SSE, and the contract has to say so.

        Previously this asserted the 501 the route returned instead of streaming. That was
        right for the world where streaming did not exist; now it does, and the same
        reasoning points the other way. `stream` is in the request schema, so generated
        clients offer it — and FastAPI infers ONE response model, so a route that can also
        answer `text/event-stream` advertises only the JSON body unless told otherwise.

        This is the mirror of 5e26dc1, where an ABI declared events the contract never
        emitted: there the schema promised what did not happen, here it would hide what
        does. Either way the generated code is confidently wrong, and neither is caught by
        tests of behaviour — only by testing the contract itself.
        """
        from app.main import app

        ok = app.openapi()["paths"]["/v1/chat/completions"]["post"]["responses"]["200"]
        assert "text/event-stream" in ok["content"], (
            "stream=true returns SSE but the OpenAPI spec advertises only JSON, "
            "so generated clients cannot know"
        )

    async def test_a_non_streaming_request_is_unaffected(
        self, client: AsyncClient, session
    ) -> None:
        """The other direction: the refusal must be about streaming, not about the field."""
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session)

        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=node_reply())):
            res = await chat(client, key, stream=False)

        assert res.status_code == 200, res.text

    async def test_confidential_tee_is_refused_rather_than_served_in_cleartext(
        self, client: AsyncClient, session
    ) -> None:
        """501, and before the node is touched.

        `data_tier` is in the schema, so a client will send `confidential_tee`. On the chat
        path it only selects an attested node and then sends the prompt down the tunnel in
        cleartext — none of the envelope encryption or attestation-gated key release the tier
        promises (that machinery is for jobs). Serving the request anyway would take money
        for a confidentiality guarantee the code does not enforce, so the honest answer is
        'not implemented' before anything is charged or dispatched. Mirror of the stream
        refusal above: do not offer what the network cannot deliver.

        Mutation guard: delete the guard in the route and this reaches dispatch — the node
        is called and the assertion on `call.assert_not_awaited()` goes red.
        """
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        # An attested node exists, so the refusal is the tier policy, not "no node to serve".
        await make_node(session, tee=True)

        call = AsyncMock()
        with patch("app.dispatch.call_provider", new=call):
            res = await chat(client, key, data_tier="confidential_tee")

        assert res.status_code == 501, res.text
        assert "confidential_tee" in res.text
        call.assert_not_awaited()  # the node's GPU was never asked to do anything

    async def test_the_default_public_tier_still_serves_on_chat(
        self, client: AsyncClient, session
    ) -> None:
        """The refusal must be about confidential_tee specifically, not about the field.

        `public` is the default every existing chat client sends, and it must be unaffected.
        """
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session)

        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=node_reply())):
            res = await chat(client, key, data_tier="public")

        assert res.status_code == 200, res.text

    async def test_unknown_model_is_404(self, client: AsyncClient, session) -> None:
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        assert (await chat(client, key, model="gpt-9-ultra")).status_code == 404

    async def test_an_image_model_is_not_a_chat_model(self, client: AsyncClient, session) -> None:
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        assert (await chat(client, key, model=IMAGE_MODEL)).status_code == 404

    async def test_no_node_serving_the_model_is_503(self, client: AsyncClient, session) -> None:
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        res = await chat(client, key)
        assert res.status_code == 503

    async def test_a_provider_key_cannot_buy_inference(self, client: AsyncClient) -> None:
        _, prov_key = await register(client, "provider", "Farm")
        assert (await chat(client, prov_key)).status_code == 403


class TestImages:
    async def test_generates_and_bills_per_image_returned(
        self, client: AsyncClient, session
    ) -> None:
        dev_id, key = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        await make_node(session, models=(IMAGE_MODEL,))

        reply = {"status": 200, "payload": {"images": ["blob://a", "blob://b"]}}
        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=reply)):
            res = await client.post(
                "/v1/images/generations",
                headers=auth(key),
                json={"model": IMAGE_MODEL, "prompt": "a cat", "n": 3},
            )

        assert res.status_code == 200, res.text
        # Asked for three, got two → billed for two. 2 × 0.01.
        assert Decimal(res.json()["cost_usdc"]) == Decimal("0.02")
        session.expire_all()
        assert await developer_balance(session, dev) == Decimal("9.98")


class TestPlacementRulesApplyOnTheV1Path:
    """The gates proven in test_dispatch.py must hold through the real endpoint too."""

    async def test_confidential_work_is_refused_on_the_v1_path_before_placement(
        self, client: AsyncClient, session
    ) -> None:
        """confidential_tee is refused (501) on the chat path before a node is chosen.

        This class used to assert the attested-only placement rule *through* the chat
        endpoint: confidential_tee got 503 with no attested node and 200 with one. That
        rule was a lie here — the endpoint selected an attested node and then sent the
        prompt in cleartext, enforcing none of the tier's confidentiality (see the refusal
        added to /v1/chat/completions). Now the tier is refused upstream, so placement is
        never reached: the attested/non-attested distinction is moot on this path, and the
        answer is 501 either way.

        The placement gate itself (confidential work → attested nodes only) is unchanged in
        `eligible_nodes`/`select_node` and is still covered at the dispatch layer in
        test_dispatch.py; it would matter through this endpoint again only if the chat path
        gains real enclave enforcement.
        """
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")

        # No attested node: old behavior was 503 (placement found nothing); now 501, before
        # placement runs at all.
        await make_node(session, tee=False)
        call = AsyncMock()
        with patch("app.dispatch.call_provider", new=call):
            res = await chat(client, key, data_tier="confidential_tee")
        assert res.status_code == 501, res.text
        call.assert_not_awaited()

        # An attested node exists: old behavior was 200; the refusal is a tier policy, not a
        # "no node" condition, so it is still 501 and the node is still untouched.
        await make_node(session, tee=True)
        with patch("app.dispatch.call_provider", new=call):
            res = await chat(client, key, data_tier="confidential_tee")
        assert res.status_code == 501, res.text
        call.assert_not_awaited()

    async def test_an_understaked_node_gets_no_v1_traffic(
        self, client: AsyncClient, session
    ) -> None:
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session, stake=0)

        assert (await chat(client, key)).status_code == 503
