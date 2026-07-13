"""Wire the chain layer into a running process (Session 13).

Both the API and the scheduler call :func:`install_chain` at startup. When ``chain_enabled`` is
false it is a no-op and the process stays fiat-only (``FiatStub``). When true it builds the real
:class:`Web3ChainClient`, registers it, and swaps in the :class:`USDCPaymentProvider` so the
submit gate reads on-chain balances. The API stops there; the scheduler additionally runs the
watcher / settlement / reconciliation loops.

Tests bypass this and install a :class:`FakeChain` directly via :func:`install_chain_client`.
"""

from __future__ import annotations

from loguru import logger

from app.chain.client import ChainClient, Web3ChainClient
from app.chain.provider import USDCPaymentProvider
from app.chain.registry import set_chain_client
from app.config import Settings
from app.payments import set_payment_provider
from app.secret_manager import get_secret_manager


def install_chain_client(settings: Settings, client: ChainClient) -> ChainClient:
    """Register ``client`` and install the USDC payment provider over it. Returns the client."""
    set_chain_client(client)
    set_payment_provider(
        USDCPaymentProvider(
            client,
            usdc_decimals=settings.usdc_decimals,
            cache_ttl_seconds=settings.chain_balance_cache_ttl_seconds,
        )
    )
    return client


def install_chain(settings: Settings) -> ChainClient | None:
    """Build + install the real chain client from settings, or ``None`` if disabled."""
    if not settings.chain_enabled:
        return None
    for name in ("chain_rpc_url", "escrow_address", "staking_address"):
        if not getattr(settings, name):
            raise ValueError(f"chain_enabled but {name} is unset")
    # Prefer Vault/secret-manager over a value in Settings: the key is fetched on demand here and
    # handed straight to the client (which needs it to sign). It is never logged or persisted on
    # Settings; the SecretStr wrapper masks any accidental repr of a value injected via env.
    key = settings.coordinator_private_key.get_secret_value() or get_secret_manager().get(
        "coordinator_private_key"
    )
    if not key:
        raise ValueError("chain_enabled but coordinator_private_key is unset")
    client = Web3ChainClient(
        rpc_url=settings.chain_rpc_url,
        chain_id=settings.chain_id,
        escrow_address=settings.escrow_address,
        staking_address=settings.staking_address,
        coordinator_private_key=key,
        log_window=settings.chain_log_window,
    )
    verify_coordinator_address(client.coordinator_address, settings.expected_coordinator_address)
    logger.info("chain layer enabled (coordinator {})", client.coordinator_address)
    return install_chain_client(settings, client)


def verify_coordinator_address(derived: str, expected: str) -> None:
    """Fail fast if the coordinator key doesn't derive to the expected on-chain role holder.

    ``expected`` is the address that actually holds COORDINATOR_ROLE on the deployed contracts. If
    it's set and the loaded key derives to a different address, we are about to sign escrow debits
    with the wrong (or a rotated-out) key — refuse to start rather than fail silently on-chain.
    Both values are public addresses; no secret is logged. Empty ``expected`` skips the check.
    """
    if expected and derived.lower() != expected.lower():
        raise ValueError(
            f"coordinator key derives to {derived} but expected_coordinator_address is {expected} "
            "— refusing to start with the wrong key"
        )
