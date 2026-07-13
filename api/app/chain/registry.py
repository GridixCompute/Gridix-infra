"""Process-wide handle to the active :class:`ChainClient` (mirrors the payment-provider seam).

``None`` means the chain layer is disabled (fiat-only): the payment provider then falls back to
pure off-chain behaviour and the chain loops don't run. Tests install a :class:`FakeChain` here.
"""

from __future__ import annotations

from app.chain.client import ChainClient

_client: ChainClient | None = None


def get_chain_client() -> ChainClient | None:
    """Return the active chain client, or ``None`` if the chain layer is disabled."""
    return _client


def set_chain_client(client: ChainClient | None) -> None:
    """Install (or clear) the active chain client."""
    global _client
    _client = client
