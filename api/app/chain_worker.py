"""Chain worker — a separate process (``python -m app.chain_worker``).

Owns the three loops that move real money on-chain:

* **watcher** — ingests confirmed deposits/withdrawals and mirrors them into the ledger.
* **settlement** — recovers in-flight settlements and pushes aggregate batches on-chain.
* **reconcile** — compares on-chain balances against the ledger and publishes divergence.

These used to run inside the scheduler process. They live here because they are not
scheduling: they are the settlement engine, and it should not share a lifecycle with a
component whose job is to hand work to providers. Splitting them means the settlement
engine can be deployed, restarted, and scaled on its own — and, more pointedly, survives
changes to how work gets dispatched.

The API and the scheduler still call ``install_chain`` themselves: it also installs the
USDC payment provider they settle escrow through. This worker is the only place that
*drives* the chain loops, not the only place that talks to the chain.
"""

import asyncio
import signal

from loguru import logger
from prometheus_client import start_http_server

from app.chain.bootstrap import install_chain
from app.chain.reconcile import Reconciler
from app.chain.registry import get_chain_client
from app.chain.settlement import SettlementEngine
from app.chain.watcher import ChainWatcher
from app.config import get_settings
from app.db import get_sessionmaker
from app.logging import configure_logging
from app.secret_manager import init_secrets


async def chain_watcher_loop(stop: asyncio.Event) -> None:
    """Ingest confirmed on-chain events (deposits/withdrawals mirror into the ledger)."""
    settings = get_settings()
    client = get_chain_client()
    if client is None:
        return
    watcher = ChainWatcher(
        client,
        get_sessionmaker(),
        usdc_decimals=settings.usdc_decimals,
        confirmations=settings.chain_confirmations,
        start_block=settings.chain_start_block,
    )
    while not stop.is_set():
        await watcher.tick()
        await asyncio.sleep(settings.chain_poll_interval_seconds)


async def settlement_loop(stop: asyncio.Event) -> None:
    """Recover in-flight settlements and push new aggregate batches on-chain (idempotent)."""
    settings = get_settings()
    client = get_chain_client()
    if client is None:
        return
    engine = SettlementEngine(
        client,
        get_sessionmaker(),
        usdc_decimals=settings.usdc_decimals,
        confirmations=settings.chain_confirmations,
        threshold_usdc=settings.settlement_threshold_usdc,
        interval_seconds=settings.settlement_interval_seconds,
    )
    # Tick often enough to confirm/recover promptly; the batch trigger itself is
    # threshold/interval-gated inside the engine, so frequent ticks don't over-settle.
    while not stop.is_set():
        await engine.tick()
        await asyncio.sleep(settings.chain_poll_interval_seconds)


async def reconcile_loop(stop: asyncio.Event) -> None:
    """Reconcile on-chain balances against the ledger; publish the divergence gauge."""
    settings = get_settings()
    client = get_chain_client()
    if client is None:
        return
    reconciler = Reconciler(client, get_sessionmaker(), usdc_decimals=settings.usdc_decimals)
    while not stop.is_set():
        await reconciler.run()
        await asyncio.sleep(settings.reconcile_interval_seconds)


def loops(stop: asyncio.Event) -> list:
    """The coroutines this worker drives. Named so a test can assert the wiring."""
    return [chain_watcher_loop(stop), settlement_loop(stop), reconcile_loop(stop)]


async def main() -> None:
    """Run the chain worker until SIGINT/SIGTERM."""
    configure_logging()
    settings = get_settings()
    # Fail fast if secrets are misconfigured — before touching money.
    init_secrets(settings)
    if not settings.chain_enabled:
        # Refuse to idle silently: a chain worker with the chain switched off is almost
        # always a deploy mistake, and a process that logs nothing looks healthy.
        logger.warning("chain worker started with chain_enabled=false — nothing to do, exiting")
        return
    await install_chain(settings)
    # Its own Prometheus scrape target, on loopback by default (pentest M7): these metrics
    # expose ledger totals and settlement state.
    start_http_server(settings.chain_worker_metrics_port, addr=settings.chain_worker_metrics_addr)
    logger.info(
        "GRIDIX chain worker starting (metrics on {}:{})",
        settings.chain_worker_metrics_addr,
        settings.chain_worker_metrics_port,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        await asyncio.gather(*loops(stop))
    finally:
        logger.info("GRIDIX chain worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
