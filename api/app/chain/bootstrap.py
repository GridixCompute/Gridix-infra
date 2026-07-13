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
    key = settings.coordinator_private_key or get_secret_manager().get("coordinator_private_key")
    if not key:
        raise ValueError("chain_enabled but coordinator_private_key is unset")
    client = Web3ChainClient(
        rpc_url=settings.chain_rpc_url,
        chain_id=settings.chain_id,
        escrow_address=settings.escrow_address,
        staking_address=settings.staking_address,
        coordinator_private_key=key,
    )
    logger.info("chain layer enabled (coordinator {})", client.coordinator_address)
    return install_chain_client(settings, client)
