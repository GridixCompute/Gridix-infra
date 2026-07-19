"""Programmatic API keys: minting, scope, revocation — and the guard that makes the
wallet/key separation mean something.

The load-bearing claim is negative: **a key cannot mint a key**. Without it, one leaked
key is permanent — the holder mints a spare, you revoke the one you know about, and they
still have access. Every other test here is about not undermining that: what a minted key
may do, whose keys a developer may see, and that revoking one actually stops it.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.models import ApiKey, ApiKeyKind
from conftest import auth, register
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient
from sqlalchemy import select
from test_inference import CHAT_MODEL, fund, make_node, node_reply

WALLET = Account.from_key("0x" + "c3" * 32)
OTHER_WALLET = Account.from_key("0x" + "d4" * 32)

KEYS = "/developers/me/keys"


@pytest.fixture(autouse=True)
def _clean_inflight():
    from app.dispatch import reset_inflight

    reset_inflight()
    yield
    reset_inflight()


async def wallet_sign_in(client: AsyncClient, account=WALLET) -> tuple[str, str]:
    """Sign in for real — recover the signature, don't fake the session.

    Returns ``(developer_id, session_key)``.
    """
    challenge = (await client.get("/auth/nonce", params={"address": account.address})).json()
    res = await client.post(
        "/auth/verify",
        json={
            "address": account.address,
            "signature": account.sign_message(
                encode_defunct(text=challenge["message"])
            ).signature.hex(),
            "nonce": challenge["nonce"],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    return body["developer_id"], body["api_key"]


async def mint(client: AsyncClient, session_key: str, label: str = "ci-runner"):
    return await client.post(KEYS, headers=auth(session_key), json={"label": label})


class TestOnlyAWalletSessionMayMint:
    """The property the whole wallet/key split rests on."""

    async def test_an_api_key_cannot_mint_another_api_key(self, client: AsyncClient) -> None:
        """The one that matters: a leaked key must not be able to make itself permanent."""
        _, session_key = await wallet_sign_in(client)
        minted = (await mint(client, session_key)).json()["api_key"]

        res = await client.post(KEYS, headers=auth(minted), json={"label": "spare"})
        assert res.status_code == 403

    async def test_a_registration_key_cannot_mint_either(self, client: AsyncClient) -> None:
        """Registration keys are programmatic too — same rule, different origin."""
        _, key = await register(client, "developer", "Acme")
        res = await client.post(KEYS, headers=auth(key), json={"label": "spare"})
        assert res.status_code == 403

    async def test_minting_requires_credentials_at_all(self, client: AsyncClient) -> None:
        assert (await client.post(KEYS, json={"label": "spare"})).status_code == 401

    async def test_a_provider_key_cannot_mint(self, client: AsyncClient) -> None:
        _, provider_key = await register(client, "provider", "Aurora GPU Farm")
        res = await client.post(KEYS, headers=auth(provider_key), json={"label": "spare"})
        assert res.status_code == 403

    async def test_listing_and_revoking_are_gated_the_same_way(self, client: AsyncClient) -> None:
        """A key that could enumerate or revoke keys would still be a foothold."""
        _, session_key = await wallet_sign_in(client)
        created = (await mint(client, session_key)).json()
        minted = created["api_key"]

        assert (await client.get(KEYS, headers=auth(minted))).status_code == 403
        assert (
            await client.delete(f"{KEYS}/{created['id']}", headers=auth(minted))
        ).status_code == 403


class TestMinting:
    async def test_returns_the_plaintext_once_and_stores_only_a_hash(
        self, client: AsyncClient, session
    ) -> None:
        _, session_key = await wallet_sign_in(client)
        res = await mint(client, session_key, label="ci-runner")
        assert res.status_code == 201, res.text
        body = res.json()

        assert body["api_key"].startswith("grdx_")
        assert body["label"] == "ci-runner"
        assert body["prefix"] == body["api_key"][:9]

        row = await session.scalar(select(ApiKey).where(ApiKey.id == uuid.UUID(body["id"])))
        assert row.key_hash != body["api_key"]
        assert body["api_key"] not in row.key_hash

        # Listing it again never re-reveals the secret.
        listed = (await client.get(KEYS, headers=auth(session_key))).json()
        assert "api_key" not in listed[0]

    async def test_a_minted_key_is_long_lived_and_programmatic(
        self, client: AsyncClient, session
    ) -> None:
        _, session_key = await wallet_sign_in(client)
        body = (await mint(client, session_key)).json()

        row = await session.scalar(select(ApiKey).where(ApiKey.id == uuid.UUID(body["id"])))
        assert row.kind is ApiKeyKind.programmatic
        assert row.expires_at is None  # a CI key that expires is a 3am outage

    async def test_a_label_is_required(self, client: AsyncClient) -> None:
        _, session_key = await wallet_sign_in(client)
        assert (await client.post(KEYS, headers=auth(session_key), json={})).status_code == 422
        res = await client.post(KEYS, headers=auth(session_key), json={"label": ""})
        assert res.status_code == 422


class TestSessionAndProgrammaticAreDistinct:
    async def test_the_two_kinds_differ_in_kind_and_lifetime(
        self, client: AsyncClient, session
    ) -> None:
        _, session_key = await wallet_sign_in(client)
        await mint(client, session_key)

        rows = (await session.scalars(select(ApiKey))).all()
        by_kind = {r.kind: r for r in rows}
        assert by_kind[ApiKeyKind.session].expires_at is not None
        assert by_kind[ApiKeyKind.programmatic].expires_at is None
        assert by_kind[ApiKeyKind.session].label == "session"

    async def test_the_browser_session_is_not_listed_as_a_programmatic_key(
        self, client: AsyncClient
    ) -> None:
        """Sessions are managed by signing in and out; listing one invites a developer to
        revoke the very credential making the request."""
        _, session_key = await wallet_sign_in(client)
        minted = (await mint(client, session_key)).json()

        listed = (await client.get(KEYS, headers=auth(session_key))).json()
        assert [k["id"] for k in listed] == [minted["id"]]

    async def test_wallet_sign_in_still_authenticates_the_browser_as_before(
        self, client: AsyncClient
    ) -> None:
        """Don't break the path the dashboard uses."""
        _, session_key = await wallet_sign_in(client)
        assert (await client.get("/jobs", headers=auth(session_key))).status_code == 200
        assert (await client.get("/v1/models", headers=auth(session_key))).status_code == 200


class TestAMintedKeyCanActuallyCallTheApi:
    """The reason this endpoint exists: buying API access you can use from a script."""

    async def test_it_authenticates_a_real_chat_completion(
        self, client: AsyncClient, session
    ) -> None:
        dev_id, session_key = await wallet_sign_in(client)
        minted = (await mint(client, session_key)).json()["api_key"]

        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session)

        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=node_reply())):
            res = await client.post(
                "/v1/chat/completions",
                headers=auth(minted),
                json={"model": CHAT_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            )

        assert res.status_code == 200, res.text
        assert res.json()["content"] == "hello"

    async def test_it_is_billed_to_the_wallet_that_minted_it(
        self, client: AsyncClient, session
    ) -> None:
        """The key inherits the minter's identity — not a new account."""
        from app.usage_billing import developer_balance

        dev_id, session_key = await wallet_sign_in(client)
        minted = (await mint(client, session_key)).json()["api_key"]

        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session)
        before = await developer_balance(session, uuid.UUID(dev_id))

        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=node_reply())):
            await client.post(
                "/v1/chat/completions",
                headers=auth(minted),
                json={"model": CHAT_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            )

        session.expire_all()
        assert await developer_balance(session, uuid.UUID(dev_id)) < before
        assert before <= Decimal("10")


class TestOwnership:
    async def test_a_developer_never_sees_another_developers_keys(
        self, client: AsyncClient
    ) -> None:
        _, mine = await wallet_sign_in(client, WALLET)
        _, theirs = await wallet_sign_in(client, OTHER_WALLET)
        await mint(client, mine, label="mine")
        await mint(client, theirs, label="theirs")

        listed = (await client.get(KEYS, headers=auth(mine))).json()
        assert [k["label"] for k in listed] == ["mine"]

    async def test_a_developer_cannot_revoke_another_developers_key(
        self, client: AsyncClient
    ) -> None:
        _, mine = await wallet_sign_in(client, WALLET)
        _, theirs = await wallet_sign_in(client, OTHER_WALLET)
        victim = (await mint(client, theirs, label="theirs")).json()

        res = await client.delete(f"{KEYS}/{victim['id']}", headers=auth(mine))
        # 404, not 403: telling them the id exists confirms another developer's credential.
        assert res.status_code == 404

        # And it still works for its owner.
        assert (await client.get("/jobs", headers=auth(victim["api_key"]))).status_code == 200

    async def test_an_unknown_key_id_is_a_404_not_a_crash(self, client: AsyncClient) -> None:
        _, session_key = await wallet_sign_in(client)
        res = await client.delete(f"{KEYS}/{uuid.uuid4()}", headers=auth(session_key))
        assert res.status_code == 404


class TestRevocation:
    async def test_a_revoked_key_stops_working_immediately(self, client: AsyncClient) -> None:
        _, session_key = await wallet_sign_in(client)
        created = (await mint(client, session_key)).json()
        minted = created["api_key"]

        assert (await client.get("/jobs", headers=auth(minted))).status_code == 200

        res = await client.delete(f"{KEYS}/{created['id']}", headers=auth(session_key))
        assert res.status_code == 204

        assert (await client.get("/jobs", headers=auth(minted))).status_code == 401
        assert (await client.get("/v1/models", headers=auth(minted))).status_code == 401

    async def test_revoking_one_key_leaves_the_others_alone(self, client: AsyncClient) -> None:
        _, session_key = await wallet_sign_in(client)
        doomed = (await mint(client, session_key, label="doomed")).json()
        spared = (await mint(client, session_key, label="spared")).json()

        await client.delete(f"{KEYS}/{doomed['id']}", headers=auth(session_key))

        assert (await client.get("/jobs", headers=auth(doomed["api_key"]))).status_code == 401
        assert (await client.get("/jobs", headers=auth(spared["api_key"]))).status_code == 200

    async def test_a_revoked_key_is_still_listed_so_it_can_be_seen(
        self, client: AsyncClient
    ) -> None:
        """Hiding it would read as "deleted" and leave no trace of what was revoked."""
        _, session_key = await wallet_sign_in(client)
        created = (await mint(client, session_key)).json()
        await client.delete(f"{KEYS}/{created['id']}", headers=auth(session_key))

        listed = (await client.get(KEYS, headers=auth(session_key))).json()
        assert [k["revoked"] for k in listed] == [True]


class TestLastUsed:
    async def test_last_used_is_recorded_when_the_key_authenticates(
        self, client: AsyncClient
    ) -> None:
        """A "last used" column nothing writes is worse than none — it reads as "never
        used" for a key that is live, which is exactly the wrong revocation decision."""
        _, session_key = await wallet_sign_in(client)
        created = (await mint(client, session_key)).json()

        listed = (await client.get(KEYS, headers=auth(session_key))).json()
        assert listed[0]["last_used_at"] is None

        assert (await client.get("/jobs", headers=auth(created["api_key"]))).status_code == 200

        listed = (await client.get(KEYS, headers=auth(session_key))).json()
        assert listed[0]["last_used_at"] is not None
