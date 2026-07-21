"""The public free tier: what bounds it, and what it must never touch.

The claim with the most at stake is NEGATIVE — a free request must leave the ledger
completely untouched. The free path exists precisely so that anonymous callers never reach
the paid dispatch path, whose only lock is a balance check that means nothing when there is
no payer. A test that only checked "free chat returns tokens" would pass just as happily if
the endpoint were quietly billing a hold against nobody, or serving the 70B model.

So the assertions here are mostly about absence: no ledger rows, no paid model, no way past
the rate limit, and no image generation while its safety control is unconfigured.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from app.dispatch import reset_inflight
from app.free_capacity import CapacityFull, FreeCapacity, reset_capacity
from app.free_tier import FREE_CHAT_MODEL, is_free_chat_model
from app.ledger import deposit_stake
from app.models import LedgerEntry, Provider, ProviderModel
from httpx import AsyncClient
from sqlalchemy import func, select

PAID_MODEL = "llama-3.1-8b"


@pytest.fixture(autouse=True)
def _clean():
    # The rate limiter's fail-closed fallback counts per (identity, minute-window) in
    # process memory, and Redis is not up in the hermetic suite — so without clearing it,
    # every test in the same minute shares one budget and the second one to run sees a
    # 429 it did not cause.
    from app.ratelimit import _local_windows

    _local_windows.clear()
    reset_inflight()
    reset_capacity()
    yield
    _local_windows.clear()
    reset_inflight()
    reset_capacity()


async def make_free_node(session, *, models=(FREE_CHAT_MODEL,)):
    now = datetime.now(UTC)
    provider = Provider(name=f"free-{uuid.uuid4().hex[:6]}", last_seen=now, connected_at=now)
    session.add(provider)
    await session.flush()
    session.add_all(ProviderModel(provider_id=provider.id, model=m) for m in models)
    await deposit_stake(session, provider.id, Decimal(1000))
    await session.commit()
    return provider


def stream_of(frames):
    async def _stream(provider_id, *, method, payload, settings, job_id=None):
        for frame in frames:
            yield frame

    return _stream


def chunk(text: str) -> dict:
    return {"type": "chunk", "delta": text, "tokens": 1}


TERMINAL = {"type": "response", "status": 200, "payload": {"usage": {}}}


async def ledger_rows(session) -> int:
    return await session.scalar(select(func.count()).select_from(LedgerEntry))


class TestTheFreePathNeverTouchesTheLedger:
    """The invariant the whole separate-path design exists to guarantee."""

    async def test_a_free_chat_posts_no_ledger_entries(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        await make_free_node(session)
        before = await ledger_rows(session)

        monkeypatch.setattr("app.routes.public.dispatch_stream", stream_of([chunk("hi"), TERMINAL]))
        res = await client.post(
            "/public/chat", json={"messages": [{"role": "user", "content": "hello"}]}
        )
        assert res.status_code == 200, res.text
        assert "hi" in res.text

        session.expire_all()
        assert await ledger_rows(session) == before, "a free request wrote to the ledger"

    async def test_the_free_path_never_reserves_or_settles(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        """Named directly, because "no ledger rows" could also mean "it failed early".

        These are the three billing calls the paid path makes. None may run here — there is
        no payer, so a hold of zero against nobody is the gate removed, not a smaller gate.
        """
        await make_free_node(session)
        monkeypatch.setattr("app.routes.public.dispatch_stream", stream_of([chunk("hi"), TERMINAL]))

        with (
            patch("app.usage_billing.reserve_balance") as reserve,
            patch("app.usage_billing.settle_reservation") as settle,
            patch("app.usage_billing.release_reservation") as release,
        ):
            res = await client.post(
                "/public/chat", json={"messages": [{"role": "user", "content": "hi"}]}
            )
            assert res.status_code == 200

        reserve.assert_not_called()
        settle.assert_not_called()
        release.assert_not_called()


class TestOnlyTheFreeModelIsReachable:
    """A free endpoint that could serve the paid catalogue is a way to get the product free."""

    async def test_the_paid_model_cannot_be_requested(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        # A node serving BOTH, so nothing but the allowlist stands between the caller and
        # the expensive model.
        await make_free_node(session, models=(FREE_CHAT_MODEL, PAID_MODEL))

        seen: dict = {}

        async def capture(provider_id, *, method, payload, settings, job_id=None):
            seen["model"] = payload["model"]
            yield chunk("x")
            yield TERMINAL

        monkeypatch.setattr("app.routes.public.dispatch_stream", capture)

        res = await client.post(
            "/public/chat",
            json={"model": PAID_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert res.status_code == 200
        assert seen["model"] == FREE_CHAT_MODEL, "the caller chose the model"

    def test_the_allowlist_is_exact_not_a_prefix(self) -> None:
        """A substring or prefix test here would BE the vulnerability."""
        assert is_free_chat_model(FREE_CHAT_MODEL)
        for other in ["llama-3.1-8b", "llama-3.1-70b", "llama3.2-3b-turbo", "llama", "", None]:
            assert not is_free_chat_model(other), other

    async def test_the_free_model_is_not_sold(self) -> None:
        """It must not be in the paid catalogue, or /v1 would price and dispatch it."""
        from app.catalog import CATALOG

        assert FREE_CHAT_MODEL not in CATALOG

    async def test_no_free_node_is_an_honest_503(self, client: AsyncClient, session) -> None:
        res = await client.post(
            "/public/chat", json={"messages": [{"role": "user", "content": "hi"}]}
        )
        assert res.status_code == 503


class TestRateLimit:
    """ "Unlimited" means no quota, not no ceiling."""

    async def test_a_flood_is_stopped(self, client: AsyncClient, session, monkeypatch) -> None:
        await make_free_node(session)
        monkeypatch.setattr("app.routes.public.dispatch_stream", stream_of([chunk("hi"), TERMINAL]))

        # Force a small limit rather than sending 30 requests: the assertion is that the
        # limit binds, not what its production value happens to be.
        async def tiny_limit(identity, limit, window_seconds=60):
            from app.ratelimit import check_rate_limit as real

            return await real(identity, 2, window_seconds)

        monkeypatch.setattr("app.routes.public.check_rate_limit", tiny_limit)

        codes = []
        for _ in range(4):
            res = await client.post(
                "/public/chat", json={"messages": [{"role": "user", "content": "hi"}]}
            )
            codes.append(res.status_code)

        assert 429 in codes, f"the flood was never refused: {codes}"
        assert codes[0] == 200, "the first request should have been served"

    async def test_the_refusal_says_when_to_come_back(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        await make_free_node(session)

        async def always_over(identity, limit, window_seconds=60):
            return False

        monkeypatch.setattr("app.routes.public.check_rate_limit", always_over)
        res = await client.post(
            "/public/chat", json={"messages": [{"role": "user", "content": "hi"}]}
        )
        assert res.status_code == 429
        assert res.headers.get("Retry-After") == "60"


# The daily image quota and the "image generation is closed" tests used to live here, when
# image generation was anonymous and bounded by a cookie+IP anchor. Images now require a
# wallet session and are counted per wallet, so those tests moved WHOLESALE to
# tests/test_image_requires_wallet.py rather than being adapted — they were describing a
# world with no identity in it, and adapting them would have kept that shape alive under new
# names. What remains here is what is still true: the free path is anonymous, unmetered
# chat that never touches the ledger.


class TestCapacity:
    """Requests queue for a slot; past the queue depth they are refused rather than parked."""

    async def test_beyond_the_slots_callers_wait(self) -> None:
        import asyncio

        capacity = FreeCapacity(slots=1, queue_depth=8)
        order: list[str] = []

        async def work(name: str, hold: asyncio.Event) -> None:
            async with capacity.slot():
                order.append(f"start:{name}")
                await hold.wait()
                order.append(f"end:{name}")

        hold_a = asyncio.Event()
        a = asyncio.create_task(work("a", hold_a))
        await asyncio.sleep(0)
        b = asyncio.create_task(work("b", asyncio.Event()))
        await asyncio.sleep(0)

        # b has not started: the single slot is held.
        assert order == ["start:a"]
        assert capacity.waiting == 1

        hold_a.set()
        await asyncio.sleep(0.01)
        assert "start:b" in order, "the queued caller never got its slot"

        b.cancel()
        await asyncio.gather(a, b, return_exceptions=True)

    async def test_past_the_queue_depth_it_refuses_rather_than_parks(self) -> None:
        import asyncio

        capacity = FreeCapacity(slots=1, queue_depth=1)
        hold = asyncio.Event()

        async def work() -> None:
            async with capacity.slot():
                await hold.wait()

        a = asyncio.create_task(work())
        await asyncio.sleep(0)
        b = asyncio.create_task(work())  # fills the one queue place
        await asyncio.sleep(0)

        with pytest.raises(CapacityFull):
            async with capacity.slot():
                pass  # pragma: no cover

        hold.set()
        b.cancel()
        await asyncio.gather(a, b, return_exceptions=True)

    async def test_a_caller_who_gives_up_releases_its_place(self) -> None:
        """Otherwise a burst of abandoned requests holds the queue against live ones."""
        import asyncio

        capacity = FreeCapacity(slots=1, queue_depth=2)
        hold = asyncio.Event()

        async def work() -> None:
            async with capacity.slot():
                await hold.wait()

        a = asyncio.create_task(work())
        await asyncio.sleep(0)
        b = asyncio.create_task(work())
        await asyncio.sleep(0)
        assert capacity.waiting == 1

        b.cancel()
        await asyncio.gather(b, return_exceptions=True)
        assert capacity.waiting == 0, "an abandoned caller kept its place in the queue"

        hold.set()
        await asyncio.gather(a, return_exceptions=True)
