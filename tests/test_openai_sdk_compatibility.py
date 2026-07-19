"""The product promise, executed: point the real OpenAI SDK at /v1 and it works.

Everything else about compatibility is asserted from our side — our tests read our JSON
with our expectations, which proves the shape we *believe* in. This proves the shape the
library actually requires, by handing a real `openai.AsyncOpenAI` a real minted key and
letting it parse a real response. If the envelope drifts by one field, the SDK raises here
rather than in a developer's terminal a week after they integrated.

Two production paths meet in this file and are only ever exercised together here:

  - the credential a developer really gets (wallet sign-in -> POST /developers/me/keys),
    not a fixture key handed out by `register()`, and
  - the response envelope /v1 really returns.

No network and no server: httpx's ASGITransport hands the SDK's requests straight to the
FastAPI app, so this runs in CI with nothing listening on a port.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from conftest import auth
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient
from openai import AsyncOpenAI
from test_inference import CHAT_MODEL, IMAGE_MODEL, fund, make_node, node_reply

WALLET = Account.from_key("0x" + "a7" * 32)

# The SDK appends /chat/completions and /images/generations to this.
BASE_URL = "http://test/v1"


@pytest.fixture(autouse=True)
def _clean_inflight():
    from app.dispatch import reset_inflight

    reset_inflight()
    yield
    reset_inflight()


async def mint_programmatic_key(client: AsyncClient) -> tuple[str, str]:
    """Get a key the way a developer actually gets one.

    Wallet sign-in for a session, then spend that session on POST /developers/me/keys —
    the only path that yields a long-lived credential, since /auth/verify hands back a
    7-day cookie session and nothing else. Returns ``(developer_id, api_key)``.
    """
    challenge = (await client.get("/auth/nonce", params={"address": WALLET.address})).json()
    verified = await client.post(
        "/auth/verify",
        json={
            "address": WALLET.address,
            "signature": WALLET.sign_message(
                encode_defunct(text=challenge["message"])
            ).signature.hex(),
            "nonce": challenge["nonce"],
        },
    )
    assert verified.status_code == 200, verified.text
    session_key = verified.json()["api_key"]

    minted = await client.post(
        "/developers/me/keys", headers=auth(session_key), json={"label": "sdk-test"}
    )
    assert minted.status_code == 201, minted.text
    return verified.json()["developer_id"], minted.json()["api_key"]


def sdk(api_key: str) -> AsyncOpenAI:
    """A real OpenAI client whose transport is the app itself.

    `max_retries=0` so a rejected request fails once and says why, instead of being
    retried into a timeout that reads like a hang.
    """
    http_client = AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test")
    return AsyncOpenAI(base_url=BASE_URL, api_key=api_key, http_client=http_client, max_retries=0)


def _app():
    from app.main import create_app

    return create_app()


class TestChatThroughTheRealSdk:
    async def test_change_the_base_url_and_it_works(self, client: AsyncClient, session) -> None:
        """The promise, end to end: a minted key, an official client, a parsed reply."""
        dev_id, api_key = await mint_programmatic_key(client)
        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session)

        openai_client = sdk(api_key)
        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=node_reply())):
            completion = await openai_client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[{"role": "user", "content": "hi there"}],
            )

        # Read through the SDK's own objects, and read ALL of them. The library does NOT
        # validate strictly — it constructs leniently, so a missing field yields an object
        # that only fails when something touches it. `create()` returning without raising
        # therefore proves nothing; these attribute accesses are the actual assertion.
        # Verified by mutation: reverting the route to the old flat shape turns this test
        # red here, while a test that merely called create() stayed green.
        assert completion.choices[0].message.content == "hello"
        assert completion.choices[0].message.role == "assistant"
        assert completion.choices[0].finish_reason in ("stop", "length")
        assert completion.model == CHAT_MODEL
        assert completion.object == "chat.completion"
        assert completion.id.startswith("chatcmpl-")
        assert completion.created > 0

        assert completion.usage is not None
        assert completion.usage.total_tokens == (
            completion.usage.prompt_tokens + completion.usage.completion_tokens
        )

    async def test_the_gridix_extras_survive_the_sdk(self, client: AsyncClient, session) -> None:
        """The extras are the reason we did not throw them away for conformance, so prove
        an OpenAI client both tolerates them and still hands them over."""
        dev_id, api_key = await mint_programmatic_key(client)
        await fund(session, uuid.UUID(dev_id), "10")
        node = await make_node(session)

        openai_client = sdk(api_key)
        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=node_reply())):
            completion = await openai_client.chat.completions.create(
                model=CHAT_MODEL, messages=[{"role": "user", "content": "hi"}]
            )

        # Unknown fields land in model_extra rather than being dropped or raising.
        extras = completion.model_extra or {}
        assert extras.get("provider_id") == str(node.id)
        assert float(extras.get("cost_usdc")) > 0

    async def test_a_revoked_key_is_refused_through_the_sdk(
        self, client: AsyncClient, session
    ) -> None:
        """Revocation has to hold on the path developers actually use, not only on ours."""
        from openai import AuthenticationError

        dev_id, api_key = await mint_programmatic_key(client)
        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session)

        session_key = await _session_key(client)
        listed = await client.get("/developers/me/keys", headers=auth(session_key))
        key_id = listed.json()[0]["id"]
        revoked = await client.delete(f"/developers/me/keys/{key_id}", headers=auth(session_key))
        assert revoked.status_code == 204

        openai_client = sdk(api_key)
        with pytest.raises(AuthenticationError):
            await openai_client.chat.completions.create(
                model=CHAT_MODEL, messages=[{"role": "user", "content": "hi"}]
            )


class TestImagesThroughTheRealSdk:
    async def test_image_generation_parses_as_an_openai_images_response(
        self, client: AsyncClient, session
    ) -> None:
        dev_id, api_key = await mint_programmatic_key(client)
        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session, models=(IMAGE_MODEL,))

        openai_client = sdk(api_key)
        reply = {"status": 200, "payload": {"images": ["blob://a"]}}
        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=reply)):
            images = await openai_client.images.generate(model=IMAGE_MODEL, prompt="a cat", n=1)

        assert images.created > 0
        assert images.data is not None
        assert images.data[0].url == "blob://a"


async def _fresh_signature(client: AsyncClient) -> dict:
    challenge = (await client.get("/auth/nonce", params={"address": WALLET.address})).json()
    return {
        "address": WALLET.address,
        "signature": WALLET.sign_message(encode_defunct(text=challenge["message"])).signature.hex(),
        "nonce": challenge["nonce"],
    }


async def _session_key(client: AsyncClient) -> str:
    res = await client.post("/auth/verify", json=await _fresh_signature(client))
    return res.json()["api_key"]
