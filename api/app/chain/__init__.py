"""On-chain settlement layer (Session 13).

The off-chain double-entry :mod:`app.ledger` stays the accounting source of truth. This
package mirrors on-chain *deposits* into the ledger and pushes *aggregate* settlements out
to the GridixEscrow / GridixStaking contracts — nothing per-job touches the chain.

Everything talks to the chain through the :class:`~app.chain.client.ChainClient` seam, so
with ``chain_enabled=False`` (the default) no RPC is ever made and the whole suite runs
hermetically against :class:`~app.chain.fake.FakeChain`.
"""
