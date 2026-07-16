"""SIWE message composition and signature recovery (EIP-4361).

Signatures here are produced by a real local account via eth_account, so the round trip
exercises actual secp256k1 — not a stub that would pass whatever we assert.
"""

from datetime import UTC, datetime

import pytest
from app.siwe import (
    build_message,
    generate_nonce,
    normalize_address,
    recover_signer,
)
from eth_account import Account
from eth_account.messages import encode_defunct

ISSUED = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)
EXPIRES = datetime(2026, 7, 16, 12, 5, 0, tzinfo=UTC)


def _account():
    return Account.from_key("0x" + "11" * 32)


def _message(address: str, *, domain: str = "app.gridix.dev", nonce: str = "abc123") -> str:
    return build_message(
        domain=domain,
        uri=f"https://{domain}",
        address=address,
        chain_id=11155111,
        nonce=nonce,
        issued_at=ISSUED,
        expires_at=EXPIRES,
    )


def _sign(message: str, account) -> str:
    return account.sign_message(encode_defunct(text=message)).signature.hex()


class TestNormalizeAddress:
    def test_checksummed_address_stores_lowercase(self) -> None:
        acct = _account()
        assert normalize_address(acct.address) == acct.address.lower()

    def test_mixed_case_and_lowercase_collapse_to_one_identity(self) -> None:
        """Two spellings of one address must never become two developer accounts."""
        acct = _account()
        assert normalize_address(acct.address) == normalize_address(acct.address.lower())

    @pytest.mark.parametrize(
        "bad",
        ["", "0x", "not-an-address", "0x1234", "0x" + "z" * 40, None, 12345],
    )
    def test_rejects_non_addresses(self, bad) -> None:
        assert normalize_address(bad) is None


class TestNonce:
    def test_is_unguessable_and_unique(self) -> None:
        nonces = {generate_nonce() for _ in range(200)}
        assert len(nonces) == 200

    def test_meets_eip4361_minimum_length(self) -> None:
        assert len(generate_nonce()) >= 8
        assert generate_nonce().isalnum()


class TestBuildMessage:
    def test_contains_the_eip4361_fields(self) -> None:
        acct = _account()
        msg = _message(acct.address)
        assert msg.startswith("app.gridix.dev wants you to sign in with your Ethereum account:")
        assert "URI: https://app.gridix.dev" in msg
        assert "Version: 1" in msg
        assert "Chain ID: 11155111" in msg
        assert "Nonce: abc123" in msg
        assert "Issued At: 2026-07-16T12:00:00Z" in msg
        assert "Expiration Time: 2026-07-16T12:05:00Z" in msg

    def test_renders_the_address_checksummed(self) -> None:
        """EIP-4361 mandates the checksummed form; it's also what the wallet shows."""
        acct = _account()
        assert acct.address in _message(acct.address.lower())


class TestRecoverSigner:
    def test_round_trips_a_real_signature(self) -> None:
        acct = _account()
        msg = _message(acct.address)
        assert recover_signer(msg, _sign(msg, acct)) == acct.address.lower()

    def test_signature_over_a_different_message_recovers_a_different_signer(self) -> None:
        """The heart of the domain check: a signature made for evil.com cannot
        authenticate here, because recovery over OUR message yields someone else."""
        acct = _account()
        evil = _message(acct.address, domain="evil.com")
        ours = _message(acct.address, domain="app.gridix.dev")
        assert recover_signer(ours, _sign(evil, acct)) != acct.address.lower()

    def test_signature_over_a_different_nonce_does_not_match(self) -> None:
        acct = _account()
        old = _message(acct.address, nonce="oldnonce")
        fresh = _message(acct.address, nonce="freshnonce")
        assert recover_signer(fresh, _sign(old, acct)) != acct.address.lower()

    def test_another_wallets_signature_does_not_match(self) -> None:
        victim = _account()
        attacker = Account.from_key("0x" + "22" * 32)
        msg = _message(victim.address)
        assert recover_signer(msg, _sign(msg, attacker)) != victim.address.lower()

    @pytest.mark.parametrize(
        "bad",
        ["", "0x", "deadbeef", "0x" + "00" * 65, "not-hex"],
    )
    def test_malformed_signatures_return_none_rather_than_raise(self, bad) -> None:
        acct = _account()
        assert recover_signer(_message(acct.address), bad) is None
