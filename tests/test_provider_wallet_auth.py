"""Provider capability from a wallet address.

Being a provider stops being a separate account with its own login and becomes a
capability attached to an address: sign in once, and the console opens if that address
owns a Provider record. The node keeps its agent key, because a node is a machine.

The claims under test:
  - an address that owns a Provider reaches the console through its wallet session
  - an address that does not is refused, not quietly served an empty console
  - one address can be a developer AND a provider
  - onboarding binds a Provider to the signed-in address and mints the node's key
  - the node's agent key keeps working on the machine surface (don't break running nodes)
  - one provider cannot read another's data through either credential
"""

import uuid

import pytest
from app.models import ApiKey, ApiKeyKind, OwnerType, Provider
from conftest import auth, register
from conftest import wallet_sign_in as siwe_sign_in
from eth_account import Account
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

WALLET = Account.from_key("0x" + "e5" * 32)
OTHER_WALLET = Account.from_key("0x" + "f6" * 32)

ONBOARD = "/providers/onboard"


async def wallet_sign_in(client: AsyncClient, account=WALLET) -> tuple[str, str]:
    """SIWE sign-in as a fixed, known wallet — this file asserts on its address."""
    return await siwe_sign_in(client, account)


async def onboard(client: AsyncClient, session_key: str, name: str = "Aurora GPU Farm"):
    return await client.post(ONBOARD, headers=auth(session_key), json={"name": name})


class TestOnboarding:
    async def test_a_wallet_session_becomes_a_provider_and_gets_a_node_key(
        self, client: AsyncClient, session
    ) -> None:
        _, session_key = await wallet_sign_in(client)
        res = await onboard(client, session_key)
        assert res.status_code == 201, res.text
        body = res.json()

        provider = await session.scalar(
            select(Provider).where(Provider.id == uuid.UUID(body["id"]))
        )
        assert provider.wallet_address == WALLET.address.lower()
        assert body["api_key"].startswith("grdx_")

    async def test_the_minted_key_is_a_machine_credential_for_the_node(
        self, client: AsyncClient, session
    ) -> None:
        _, session_key = await wallet_sign_in(client)
        body = (await onboard(client, session_key)).json()

        key = await session.scalar(
            select(ApiKey).where(ApiKey.provider_id == uuid.UUID(body["id"]))
        )
        assert key.owner_type is OwnerType.provider
        assert key.label == "node agent"
        # Programmatic, so require_wallet_session refuses it: a node cannot mint keys.
        assert key.kind is ApiKeyKind.programmatic

    async def test_an_api_key_cannot_onboard_a_provider(self, client: AsyncClient) -> None:
        """Onboarding mints a credential, so it must not be reachable with a credential.

        Otherwise a leaked developer key stands up a node and walks away with its agent
        key — exactly the permanence that revoking the leaked key is supposed to end.
        """
        _, session_key = await wallet_sign_in(client)
        minted = (
            await client.post(
                "/developers/me/keys", headers=auth(session_key), json={"label": "ci"}
            )
        ).json()["api_key"]

        res = await client.post(ONBOARD, headers=auth(minted), json={"name": "Sneaky Farm"})
        assert res.status_code == 403

    async def test_onboarding_requires_credentials_at_all(self, client: AsyncClient) -> None:
        assert (await client.post(ONBOARD, json={"name": "Anon Farm"})).status_code == 401

    async def test_one_address_cannot_hold_two_providers(self, client: AsyncClient) -> None:
        """A second record would split earnings and reputation across one identity."""
        _, session_key = await wallet_sign_in(client)
        assert (await onboard(client, session_key)).status_code == 201
        assert (await onboard(client, session_key, name="Second Farm")).status_code == 409


class TestConsoleOpensOnTheAddress:
    async def test_the_owning_address_reaches_the_console_with_its_wallet_session(
        self, client: AsyncClient
    ) -> None:
        _, session_key = await wallet_sign_in(client)
        await onboard(client, session_key)

        res = await client.get("/providers/me", headers=auth(session_key))
        assert res.status_code == 200
        assert res.json()["name"] == "Aurora GPU Farm"

    async def test_an_address_with_no_provider_is_refused(self, client: AsyncClient) -> None:
        """Refused, not served an empty console: "you have no earnings" and "you are not
        registered" are very different things to an operator."""
        _, session_key = await wallet_sign_in(client)
        assert (await client.get("/providers/me", headers=auth(session_key))).status_code == 403

    async def test_the_whole_console_surface_opens_not_just_one_route(
        self, client: AsyncClient
    ) -> None:
        _, session_key = await wallet_sign_in(client)
        await onboard(client, session_key)

        for path in (
            "/providers/me/bandwidth",
            "/providers/me/benchmark",
            "/providers/me/jobs",
            "/providers/me/reputation",
            "/providers/me/trust",
            "/disputes/me",
        ):
            res = await client.get(path, headers=auth(session_key))
            assert res.status_code == 200, f"{path} -> {res.status_code} {res.text}"

    async def test_capabilities_can_be_declared_from_the_console(self, client: AsyncClient) -> None:
        _, session_key = await wallet_sign_in(client)
        await onboard(client, session_key)

        res = await client.patch(
            "/providers/me", headers=auth(session_key), json={"gpu_model": "RTX A4500"}
        )
        assert res.status_code == 200
        assert res.json()["gpu_model"] == "RTX A4500"


class TestOneAddressTwoCapabilities:
    async def test_the_same_address_is_both_developer_and_provider(
        self, client: AsyncClient
    ) -> None:
        """The design claim: one identity, two capabilities — not two accounts."""
        _, session_key = await wallet_sign_in(client)
        await onboard(client, session_key)

        # Developer side, on the very same session.
        assert (await client.get("/jobs", headers=auth(session_key))).status_code == 200
        assert (await client.get("/v1/models", headers=auth(session_key))).status_code == 200
        # Provider side.
        assert (await client.get("/providers/me", headers=auth(session_key))).status_code == 200

    async def test_being_a_provider_does_not_require_giving_up_the_developer_side(
        self, client: AsyncClient, session
    ) -> None:
        dev_id, session_key = await wallet_sign_in(client)
        await onboard(client, session_key)

        provider = await session.scalar(
            select(Provider).where(Provider.wallet_address == WALLET.address.lower())
        )
        # Two rows, one address — the developer was not converted into a provider.
        assert provider is not None
        assert str(provider.id) != dev_id


class TestTheNodeKeepsWorking:
    """Nodes are machines and keep their agent key. Breaking this takes the network down."""

    async def test_the_agent_key_still_reaches_the_machine_surface(
        self, client: AsyncClient
    ) -> None:
        _, session_key = await wallet_sign_in(client)
        node_key = (await onboard(client, session_key)).json()["api_key"]

        assert (await client.post("/agent/ping", headers=auth(node_key))).status_code == 200
        assert (await client.post("/agent/poll", headers=auth(node_key))).status_code == 200

    async def test_the_agent_key_still_reaches_the_console(self, client: AsyncClient) -> None:
        _, session_key = await wallet_sign_in(client)
        node_key = (await onboard(client, session_key)).json()["api_key"]

        assert (await client.get("/providers/me", headers=auth(node_key))).status_code == 200

    async def test_a_wallet_session_cannot_drive_the_machine_surface(
        self, client: AsyncClient
    ) -> None:
        """A browser has no business claiming jobs or uploading results."""
        _, session_key = await wallet_sign_in(client)
        await onboard(client, session_key)

        assert (await client.post("/agent/poll", headers=auth(session_key))).status_code == 403


class TestIsolation:
    async def test_one_provider_never_sees_another_through_a_wallet_session(
        self, client: AsyncClient
    ) -> None:
        _, mine = await wallet_sign_in(client, WALLET)
        _, theirs = await wallet_sign_in(client, OTHER_WALLET)
        await onboard(client, mine, name="Mine")
        await onboard(client, theirs, name="Theirs")

        assert (await client.get("/providers/me", headers=auth(mine))).json()["name"] == "Mine"
        assert (await client.get("/providers/me", headers=auth(theirs))).json()["name"] == "Theirs"

    async def test_a_developer_key_of_one_address_cannot_reach_another_providers_console(
        self, client: AsyncClient
    ) -> None:
        _, theirs = await wallet_sign_in(client, OTHER_WALLET)
        await onboard(client, theirs, name="Theirs")

        # A different address, with no provider of its own.
        _, mine = await wallet_sign_in(client, WALLET)
        assert (await client.get("/providers/me", headers=auth(mine))).status_code == 403

    async def test_a_plain_registration_key_cannot_reach_the_console_of_a_wallet_provider(
        self, client: AsyncClient
    ) -> None:
        _, session_key = await wallet_sign_in(client)
        wallet_provider = (await onboard(client, session_key)).json()

        _, stranger_key = await register(client, "developer", "Stranger")
        res = await client.get("/providers/me", headers=auth(stranger_key))
        assert res.status_code == 403

        # And the legitimate owner still resolves to their own record.
        assert (await client.get("/providers/me", headers=auth(session_key))).json()[
            "id"
        ] == wallet_provider["id"]


class TestWalletLessProvidersCannotExist:
    """The hazard TestLegacyProvidersWithoutAWallet used to pin, now closed at both layers.

    POST /providers minted providers with wallet_address NULL — records no wallet session
    could ever reach. The route is gone, and providers.wallet_address is NOT NULL
    (migration 0025), so the database itself rejects any construction path someone
    re-introduces. Deleted before any deploy: zero such rows ever existed.
    """

    async def test_the_legacy_registration_route_is_gone(self, client: AsyncClient) -> None:
        res = await client.post("/providers", json={"name": "Legacy Farm"})
        assert res.status_code == 404

    async def test_a_provider_cannot_be_persisted_without_a_wallet_address(self, session) -> None:
        """The mutation check: re-adding a wallet-less factory fails at the schema."""
        session.add(Provider(name="orphan"))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.parametrize("path", ["/providers/me", "/disputes/me"])
async def test_console_routes_still_reject_anonymous_callers(
    client: AsyncClient, path: str
) -> None:
    assert (await client.get(path)).status_code == 401
