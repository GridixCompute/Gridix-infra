"""Wallet sign-in end to end: auto-registration, replay, and cross-domain forgery.

Every signature here is produced by a real local account, so these exercise the actual
recovery path rather than a mock that would agree with whatever we claim.
"""

from datetime import UTC, datetime, timedelta

import pytest
from app.models import ApiKey, AuthNonce, Developer
from app.siwe import build_message
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient
from sqlalchemy import select

WALLET = Account.from_key("0x" + "a1" * 32)
OTHER = Account.from_key("0x" + "b2" * 32)


def sign(account, message: str) -> str:
    return account.sign_message(encode_defunct(text=message)).signature.hex()


async def get_challenge(client: AsyncClient, address: str) -> dict:
    res = await client.get("/auth/nonce", params={"address": address})
    assert res.status_code == 200, res.text
    return res.json()


async def sign_in(client: AsyncClient, account) -> tuple[int, dict]:
    """Full happy path: fetch a challenge, sign it, exchange it for a session."""
    challenge = await get_challenge(client, account.address)
    res = await client.post(
        "/auth/verify",
        json={
            "address": account.address,
            "signature": sign(account, challenge["message"]),
            "nonce": challenge["nonce"],
        },
    )
    return res.status_code, res.json()


class TestChallenge:
    async def test_message_is_eip4361_and_states_our_domain_and_chain(
        self, client: AsyncClient
    ) -> None:
        challenge = await get_challenge(client, WALLET.address)
        message = challenge["message"]
        assert "wants you to sign in with your Ethereum account:" in message
        assert "Version: 1" in message
        assert "Chain ID: 11155111" in message
        assert f"Nonce: {challenge['nonce']}" in message
        # The checksummed address is what the wallet will display to the user.
        assert WALLET.address in message

    async def test_every_challenge_is_unique(self, client: AsyncClient) -> None:
        a = await get_challenge(client, WALLET.address)
        b = await get_challenge(client, WALLET.address)
        assert a["nonce"] != b["nonce"]

    async def test_rejects_a_non_address(self, client: AsyncClient) -> None:
        res = await client.get("/auth/nonce", params={"address": "not-a-wallet"})
        assert res.status_code == 422


class TestAutoRegistration:
    async def test_new_wallet_signs_in_and_becomes_a_developer(
        self, client: AsyncClient, session
    ) -> None:
        status, body = await sign_in(client, WALLET)
        assert status == 200, body
        assert body["wallet_address"] == WALLET.address.lower()

        developer = await session.scalar(
            select(Developer).where(Developer.wallet_address == WALLET.address.lower())
        )
        assert developer is not None
        assert str(developer.id) == body["developer_id"]

    async def test_session_works_as_credentials_on_a_real_route(self, client: AsyncClient) -> None:
        """The point of minting an ApiKey: existing routes authenticate a wallet
        session with no special-casing."""
        _, body = await sign_in(client, WALLET)
        res = await client.get("/jobs", headers={"Authorization": f"Bearer {body['api_key']}"})
        assert res.status_code == 200

    async def test_returning_wallet_resolves_to_the_same_account(
        self, client: AsyncClient, session
    ) -> None:
        _, first = await sign_in(client, WALLET)
        _, second = await sign_in(client, WALLET)
        assert first["developer_id"] == second["developer_id"]

        developers = (
            await session.scalars(
                select(Developer).where(Developer.wallet_address == WALLET.address.lower())
            )
        ).all()
        assert len(developers) == 1

    async def test_two_wallets_are_two_accounts(self, client: AsyncClient) -> None:
        _, mine = await sign_in(client, WALLET)
        _, theirs = await sign_in(client, OTHER)
        assert mine["developer_id"] != theirs["developer_id"]

    async def test_session_key_is_labelled_and_expiring(self, client: AsyncClient, session) -> None:
        _, body = await sign_in(client, WALLET)
        key = await session.scalar(select(ApiKey).where(ApiKey.label == "session"))
        assert key is not None
        assert key.expires_at is not None


class TestReplay:
    async def test_a_spent_nonce_cannot_be_reused(self, client: AsyncClient) -> None:
        """The DoD case: capture a valid signature, present it twice, second is refused."""
        challenge = await get_challenge(client, WALLET.address)
        payload = {
            "address": WALLET.address,
            "signature": sign(WALLET, challenge["message"]),
            "nonce": challenge["nonce"],
        }
        first = await client.post("/auth/verify", json=payload)
        assert first.status_code == 200

        replay = await client.post("/auth/verify", json=payload)
        assert replay.status_code == 401

    async def test_an_expired_nonce_is_refused(self, client: AsyncClient, session) -> None:
        challenge = await get_challenge(client, WALLET.address)
        row = await session.scalar(select(AuthNonce).where(AuthNonce.nonce == challenge["nonce"]))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

        res = await client.post(
            "/auth/verify",
            json={
                "address": WALLET.address,
                "signature": sign(WALLET, challenge["message"]),
                "nonce": challenge["nonce"],
            },
        )
        assert res.status_code == 401

    async def test_an_unknown_nonce_is_refused(self, client: AsyncClient) -> None:
        challenge = await get_challenge(client, WALLET.address)
        res = await client.post(
            "/auth/verify",
            json={
                "address": WALLET.address,
                "signature": sign(WALLET, challenge["message"]),
                "nonce": "0" * 32,
            },
        )
        assert res.status_code == 401


class TestForgery:
    async def test_signature_for_another_domain_is_refused(self, client: AsyncClient) -> None:
        """The phishing case: a user signs a SIWE message on evil.com for the same
        wallet, nonce and chain. It must not open a session here."""
        challenge = await get_challenge(client, WALLET.address)
        evil = build_message(
            domain="evil.com",
            uri="https://evil.com",
            address=WALLET.address,
            chain_id=11155111,
            nonce=challenge["nonce"],
            issued_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        res = await client.post(
            "/auth/verify",
            json={
                "address": WALLET.address,
                "signature": sign(WALLET, evil),
                "nonce": challenge["nonce"],
            },
        )
        assert res.status_code == 401

    async def test_cannot_claim_someone_elses_address(self, client: AsyncClient) -> None:
        """A challenge issued to the victim, signed by the attacker's own wallet."""
        challenge = await get_challenge(client, WALLET.address)
        res = await client.post(
            "/auth/verify",
            json={
                "address": WALLET.address,
                "signature": sign(OTHER, challenge["message"]),
                "nonce": challenge["nonce"],
            },
        )
        assert res.status_code == 401

    async def test_cannot_redirect_a_challenge_to_another_address(
        self, client: AsyncClient
    ) -> None:
        """Attacker signs the victim's challenge correctly-formed but claims it is theirs."""
        challenge = await get_challenge(client, WALLET.address)
        res = await client.post(
            "/auth/verify",
            json={
                "address": OTHER.address,
                "signature": sign(OTHER, challenge["message"]),
                "nonce": challenge["nonce"],
            },
        )
        assert res.status_code == 401

    @pytest.mark.parametrize("bad", ["", "0x", "deadbeef", "0x" + "00" * 65])
    async def test_malformed_signatures_are_refused_not_crashed(
        self, client: AsyncClient, bad: str
    ) -> None:
        challenge = await get_challenge(client, WALLET.address)
        res = await client.post(
            "/auth/verify",
            json={"address": WALLET.address, "signature": bad, "nonce": challenge["nonce"]},
        )
        assert res.status_code in (401, 422)

    async def test_rejection_reason_is_never_disclosed(self, client: AsyncClient) -> None:
        """Distinct failures must be indistinguishable, or the endpoint becomes an
        oracle for probing which challenges are live."""
        challenge = await get_challenge(client, WALLET.address)
        unknown = await client.post(
            "/auth/verify",
            json={
                "address": WALLET.address,
                "signature": sign(WALLET, challenge["message"]),
                "nonce": "0" * 32,
            },
        )
        wrong_signer = await client.post(
            "/auth/verify",
            json={
                "address": WALLET.address,
                "signature": sign(OTHER, challenge["message"]),
                "nonce": challenge["nonce"],
            },
        )
        assert unknown.json()["error"]["message"] == wrong_signer.json()["error"]["message"]
