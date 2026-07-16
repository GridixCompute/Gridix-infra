"""The chain worker actually drives the money loops.

These exist because tests/test_session13_chain_settlement.py cannot prove it: that suite
constructs ChainWatcher / SettlementEngine / Reconciler and calls them directly, so it
stays green whether or not anything in production ever runs them. Moving the loops out of
the scheduler with only that suite as cover would look identical to deleting them.

So: assert the engines get ticked *by the worker's loops*, and that the scheduler no
longer carries them.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from app import scheduler
from app.chain.fake import FakeChain
from app.chain.reconcile import Reconciler
from app.chain.registry import set_chain_client
from app.chain.settlement import SettlementEngine
from app.chain.watcher import ChainWatcher
from app.chain_worker import (
    chain_watcher_loop,
    loops,
    main,
    reconcile_loop,
    settlement_loop,
)


@pytest.fixture(autouse=True)
def _no_chain_client():
    """Every test states its own chain client; none leaks into the next."""
    yield
    set_chain_client(None)


async def _run_until_first_tick(loop_fn, engine_cls: type, method: str) -> int:
    """Run ``loop_fn`` until its engine is ticked once, then stop it.

    asyncio.sleep is stubbed so the loop doesn't idle for the poll interval between the
    tick and noticing the stop event.
    """
    stop = asyncio.Event()
    calls = 0

    async def _tick(_self, *args, **kwargs):
        nonlocal calls
        calls += 1
        stop.set()

    with (
        patch.object(engine_cls, method, _tick),
        patch("app.chain_worker.asyncio.sleep", new=AsyncMock()),
    ):
        await asyncio.wait_for(loop_fn(stop), timeout=5)
    return calls


class TestLoopsDriveTheirEngines:
    async def test_watcher_loop_ticks_the_watcher(self) -> None:
        set_chain_client(FakeChain())
        assert await _run_until_first_tick(chain_watcher_loop, ChainWatcher, "tick") == 1

    async def test_settlement_loop_ticks_the_engine(self) -> None:
        set_chain_client(FakeChain())
        assert await _run_until_first_tick(settlement_loop, SettlementEngine, "tick") == 1

    async def test_reconcile_loop_runs_the_reconciler(self) -> None:
        set_chain_client(FakeChain())
        assert await _run_until_first_tick(reconcile_loop, Reconciler, "run") == 1

    async def test_loops_keep_ticking_until_stopped(self) -> None:
        """One tick proves wiring; repetition proves it is a loop and not a one-shot."""
        set_chain_client(FakeChain())
        stop = asyncio.Event()
        calls = 0

        async def _tick(_self):
            nonlocal calls
            calls += 1
            if calls == 3:
                stop.set()

        with (
            patch.object(ChainWatcher, "tick", _tick),
            patch("app.chain_worker.asyncio.sleep", new=AsyncMock()),
        ):
            await asyncio.wait_for(chain_watcher_loop(stop), timeout=5)
        assert calls == 3


class TestNoChainClient:
    @pytest.mark.parametrize("loop_fn", [chain_watcher_loop, settlement_loop, reconcile_loop])
    async def test_loop_returns_immediately_without_a_client(self, loop_fn) -> None:
        """chain_enabled=false leaves no client installed; the loops must not spin."""
        set_chain_client(None)
        await asyncio.wait_for(loop_fn(asyncio.Event()), timeout=2)


class TestWiring:
    def test_worker_drives_all_three_loops(self) -> None:
        names = {c.cr_code.co_name for c in loops(asyncio.Event())}
        assert names == {"chain_watcher_loop", "settlement_loop", "reconcile_loop"}
        # Close them; they were never awaited.
        for c in loops(asyncio.Event()):
            c.close()

    async def test_main_refuses_to_idle_when_the_chain_is_disabled(self) -> None:
        """A chain worker with chain_enabled=false is a deploy mistake. It must exit,
        not sit there looking healthy."""
        with (
            patch("app.chain_worker.init_secrets"),
            patch("app.chain_worker.install_chain") as install,
            patch("app.chain_worker.start_http_server") as metrics,
        ):
            await asyncio.wait_for(main(), timeout=5)
        # get_settings() is the hermetic suite's: chain_enabled defaults to false.
        install.assert_not_called()
        metrics.assert_not_called()


class TestSchedulerNoLongerOwnsTheMoney:
    @pytest.mark.parametrize("gone", ["_chain_watcher_loop", "_settlement_loop", "_reconcile_loop"])
    def test_chain_loops_are_not_in_the_scheduler(self, gone: str) -> None:
        assert not hasattr(scheduler, gone)

    def test_scheduler_still_installs_the_chain(self) -> None:
        """install_chain also registers the USDC payment provider that this process
        settles escrow through — moving the loops out must not take it along, or
        settlement silently falls back to the fiat stub.
        """
        assert hasattr(scheduler, "install_chain")
