"""Streamed chat completions: the SSE shape, and the money when a stream does not finish.

The billing is the reason this file is long. A unary request has two outcomes and the hold
is resolved in the same breath as the reply. A stream has three, only one of which reaches
the end of the generator:

  * the node finishes        -> settle for the reported usage
  * the CLIENT disconnects   -> settle for the tokens actually produced, release the rest
  * the node fails mid-way   -> release the whole hold

The middle one gets the most coverage here because it is the one with no natural place to
run: the code that resolves the hold is running inside the task that was just cancelled. Get
it wrong and the hold sits in escrow forever, which nothing downstream can detect or repair
— the developer's balance is simply, permanently, short.

The stream body is driven directly rather than through the ASGI client. A streaming response
cannot be consumed incrementally through the in-process transport, and a disconnect can only
be produced by closing the generator by hand — which is exactly what a real disconnect does.
"""

import asyncio
import json
import uuid
from decimal import Decimal

import pytest
from app.catalog import get_model
from app.db import get_sessionmaker
from app.dispatch import reset_inflight
from app.ledger import account_balance, deposit_stake
from app.models import LedgerAccount, Provider, ProviderModel
from app.streaming_chat import chat_stream_body
from app.usage_billing import credit_deposit, developer_balance, reserve_balance
from conftest import register
from httpx import AsyncClient

CHAT_MODEL = "llama-3.1-8b"


@pytest.fixture(autouse=True)
def _clean_inflight():
    reset_inflight()
    yield
    reset_inflight()


async def make_node(session, *, models=(CHAT_MODEL,), stake=1000):
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    provider = Provider(name=f"node-{uuid.uuid4().hex[:6]}", last_seen=now, connected_at=now)
    session.add(provider)
    await session.flush()
    session.add_all(ProviderModel(provider_id=provider.id, model=m) for m in models)
    await deposit_stake(session, provider.id, Decimal(stake))
    await session.commit()
    return provider


def chunk(delta: str, tokens: int | None = None) -> dict:
    frame = {"type": "chunk", "request_id": "r", "delta": delta}
    if tokens is not None:
        frame["tokens"] = tokens
    return frame


def terminal(*, prompt=10, completion=4, content="hi") -> dict:
    return {
        "type": "response",
        "request_id": "r",
        "status": 200,
        "payload": {
            "content": content,
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
        },
    }


def fake_stream(frames, *, hold_open: asyncio.Event | None = None):
    """A stand-in for ``dispatch_stream`` that yields ``frames``.

    ``hold_open`` parks the generator after the frames run out, which is what a real node
    mid-generation looks like: chunks have arrived, the terminal frame has not, and the
    coordinator is waiting. That is the state a client disconnect has to be safe in.
    """

    async def _stream(provider_id, *, method, payload, settings, job_id=None):
        for frame in frames:
            yield frame
            await asyncio.sleep(0)  # let the consumer run between frames
        if hold_open is not None:
            await hold_open.wait()

    return _stream


async def drive(monkeypatch, frames, *, developer_id, provider_id, held, hold_open=None, **kw):
    """Build a stream body over ``frames`` with the billing wired to real ledger calls."""
    monkeypatch.setattr(
        "app.streaming_chat.dispatch_stream", fake_stream(frames, hold_open=hold_open)
    )
    spec = get_model(CHAT_MODEL)
    from app.config import get_settings

    params = {
        "spec": spec,
        "model": CHAT_MODEL,
        "payload": {"model": CHAT_MODEL, "messages": []},
        "developer_id": developer_id,
        "provider_id": provider_id,
        "held": held,
        "worst_case": held,
        "prompt_tokens": 10,
        "max_output": 100,
        "created": 0,
        "settings": get_settings(),
    }
    params.update(kw)
    return chat_stream_body(**params)


def data_events(frames: list[str]) -> list[dict | str]:
    """Parse SSE text frames into their payloads, keeping ``[DONE]`` as the literal token."""
    out: list[dict | str] = []
    for frame in frames:
        assert frame.startswith("data: "), frame
        body = frame[len("data: ") :].strip()
        out.append(body if body == "[DONE]" else json.loads(body))
    return out


async def escrow_balance(session, developer_id) -> Decimal:
    """What is still held for this developer. Must be zero once a request is resolved."""
    return await account_balance(session, LedgerAccount.escrow, developer_id)


async def setup_funded(client: AsyncClient, session, amount="10") -> tuple[uuid.UUID, uuid.UUID]:
    dev_id, _ = await register(client, "developer", "Acme")
    developer_id = uuid.UUID(dev_id)
    await credit_deposit(session, developer_id=developer_id, amount=Decimal(amount))
    await session.commit()
    provider = await make_node(session)
    return developer_id, provider.id


class TestNormalStream:
    """The happy path: OpenAI-shaped chunks, progressively, ending in [DONE]."""

    async def test_chunks_arrive_before_the_stream_ends(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        """Progressive delivery is the whole feature.

        A generator that buffered everything and emitted it at the end would satisfy every
        shape assertion below while being, precisely, not streaming. So this consumes one
        frame at a time and asserts content arrives while the node is still going — the node
        here never sends its terminal frame until the test lets it.
        """
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("0.001"))

        hold_open = asyncio.Event()
        body = await drive(
            monkeypatch,
            [chunk("Hel"), chunk("lo")],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            hold_open=hold_open,
        )

        seen = []
        agen = body.__aiter__()
        for _ in range(3):  # role delta + two content chunks
            seen.append(await agen.__anext__())

        events = data_events(seen)
        assert events[0]["choices"][0]["delta"] == {"role": "assistant"}
        assert events[1]["choices"][0]["delta"] == {"content": "Hel"}
        assert events[2]["choices"][0]["delta"] == {"content": "lo"}
        # Still mid-generation: nothing has been settled, the hold is intact.
        session.expire_all()
        assert await escrow_balance(session, developer_id) == held

        hold_open.set()
        await body.aclose()

    async def test_shape_is_openai_and_ends_with_done(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("0.001"))

        body = await drive(
            monkeypatch,
            [chunk("a"), chunk("b"), terminal(prompt=10, completion=2)],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
        )
        events = data_events([f async for f in body])

        assert events[-1] == "[DONE]"
        for event in events[:-1]:
            assert event["object"] == "chat.completion.chunk"
        # A finish_reason lands exactly once, on the frame that closes the choice.
        finishes = [
            c["finish_reason"]
            for e in events[:-1]
            if isinstance(e, dict)
            for c in e.get("choices", [])
            if c.get("finish_reason")
        ]
        assert finishes == ["stop"]

    async def test_the_final_event_bills_what_the_node_reported(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        """The usage the node reports is what is charged, and the client is told the price."""
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))

        body = await drive(
            monkeypatch,
            [chunk("a"), terminal(prompt=500, completion=1000)],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            worst_case=Decimal("1"),
            max_output=1000,
        )
        events = data_events([f async for f in body])

        usage_event = next(e for e in events[:-1] if isinstance(e, dict) and "usage" in e)
        assert usage_event["usage"] == {
            "prompt_tokens": 500,
            "completion_tokens": 1000,
            "total_tokens": 1500,
        }
        # 500 in @ 0.05/Mtok + 1000 out @ 0.08/Mtok = 0.000105 USDC, same as the unary path.
        assert Decimal(usage_event["cost_usdc"]) == Decimal("0.000105")

        session.expire_all()
        assert await developer_balance(session, developer_id) == Decimal("9.999895")
        assert await escrow_balance(session, developer_id) == 0


class TestClientDisconnect:
    """The dangerous case: the caller hangs up while the node is still generating.

    Closing the generator is what a disconnect does — Starlette closes the response body
    when the connection drops, which raises GeneratorExit at the pending yield. Everything
    below happens inside that teardown, which is why it is fragile enough to deserve this
    much coverage.
    """

    async def test_partial_tokens_are_billed_and_the_rest_released(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        """The provider is paid for what it produced; the developer keeps the remainder.

        Neither half is optional. Refunding everything would make "start a stream and hang
        up" a free way to burn someone's GPU; charging the full hold would bill for tokens
        that were never generated.
        """
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))

        hold_open = asyncio.Event()
        body = await drive(
            monkeypatch,
            [chunk("a", tokens=1), chunk("b", tokens=2), chunk("c", tokens=3)],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            hold_open=hold_open,
            worst_case=Decimal("1"),
        )

        agen = body.__aiter__()
        for _ in range(4):  # role delta + three chunks
            await agen.__anext__()

        await body.aclose()  # the client is gone
        hold_open.set()
        await asyncio.sleep(0)  # let the shielded finaliser run

        session.expire_all()
        # 10 prompt @ 0.05/Mtok + 3 completion @ 0.08/Mtok = 0.00000074 -> 0.000001 quantised.
        charged = Decimal("10") - await developer_balance(session, developer_id)
        assert charged > 0, "a provider that generated tokens must be paid for them"
        assert charged < Decimal("1"), "the unused remainder of the hold must come back"
        assert await escrow_balance(session, developer_id) == 0, "hold left stranded in escrow"

    async def test_no_hold_is_stranded_when_the_client_vanishes(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        """Zero holds outstanding, and the ledger still balances.

        This is the invariant with no recovery path: a hold nobody releases is money the
        developer cannot spend and no later request knows to return.
        """
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))
        assert await escrow_balance(session, developer_id) == held  # precondition

        hold_open = asyncio.Event()
        body = await drive(
            monkeypatch,
            [chunk("a", tokens=1)],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            hold_open=hold_open,
            worst_case=Decimal("1"),
        )
        agen = body.__aiter__()
        await agen.__anext__()
        await agen.__anext__()
        await body.aclose()
        hold_open.set()
        await asyncio.sleep(0)

        session.expire_all()
        assert await escrow_balance(session, developer_id) == 0

        # And the books balance for this request: what left the developer arrived somewhere.
        # Asserted as a delta rather than a global sum because the fixtures also fund a
        # deposit and a provider stake, whose postings are not this request's business.
        async with get_sessionmaker()() as fresh:
            charged = Decimal("10") - await account_balance(
                fresh, LedgerAccount.developer, developer_id
            )
            earned = await account_balance(fresh, LedgerAccount.provider, provider_id)
            fees = await account_balance(fresh, LedgerAccount.protocol)
        # The protocol account is debited by the deposit and the stake that funded the
        # fixtures, so its fee share is whatever it holds ABOVE that starting position.
        fee_share = fees - Decimal("-1010")
        assert charged > 0
        assert charged == earned + fee_share, "the charge did not land in provider + protocol"

    async def test_a_cancelled_task_still_resolves_the_hold(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        """The real disconnect: the TASK reading the stream is cancelled.

        Cancelled through an anyio CANCEL SCOPE, not `task.cancel()`, and the difference is
        the whole point. Starlette runs a streaming response inside an anyio task group, and
        anyio scopes are LEVEL-triggered: once the scope is cancelled, every subsequent
        `await` inside it raises CancelledError again. A bare asyncio `task.cancel()` is
        edge-triggered — it delivers CancelledError once, after which the `finally` can
        happily await — so a test built on it passes with or without the shield and proves
        nothing about production.

        Under a cancel scope, an unshielded settle in the `finally` raises before it can
        post anything, and the hold is stranded in escrow forever with nothing downstream
        able to detect or repair it. This is the test that holds `_run_shielded` up.
        """
        import anyio
        from app.streaming_chat import _finalisers

        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))

        hold_open = asyncio.Event()
        reading = asyncio.Event()
        body = await drive(
            monkeypatch,
            [chunk("a", tokens=1), chunk("b", tokens=2)],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            hold_open=hold_open,
            worst_case=Decimal("1"),
        )

        scopes: dict[str, anyio.CancelScope] = {}

        async def consume() -> None:
            # The scope lives INSIDE the consuming task, exactly as Starlette's does: the
            # stream body runs within it, so cancelling the scope cancels every await the
            # body makes — including the ones in its cleanup.
            with anyio.CancelScope() as scope:
                scopes["it"] = scope
                async for _ in body:
                    reading.set()

        task = asyncio.create_task(consume())
        await asyncio.wait_for(reading.wait(), timeout=2)
        await asyncio.sleep(0)  # let both chunks land, then park on hold_open

        scopes["it"].cancel()
        await asyncio.gather(task, return_exceptions=True)

        # The finaliser outlives the cancelled scope by design; wait for it as production's
        # event loop would.
        if _finalisers:
            await asyncio.gather(*list(_finalisers), return_exceptions=True)
        hold_open.set()

        session.expire_all()
        assert await escrow_balance(session, developer_id) == 0, (
            "the hold survived a cancelled task — it is stranded in escrow forever"
        )
        charged = Decimal("10") - await developer_balance(session, developer_id)
        assert charged > 0, "the provider generated tokens and was not paid"

    async def test_disconnecting_before_any_token_charges_nothing(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        """No tokens produced, no charge — but still no stranded hold.

        The boundary of the rule above: paying a provider for a generation that produced
        nothing would be as wrong as not paying it for one that produced something.
        """
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))

        hold_open = asyncio.Event()
        body = await drive(
            monkeypatch,
            [],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            hold_open=hold_open,
            worst_case=Decimal("1"),
        )
        agen = body.__aiter__()
        await agen.__anext__()  # the role delta, nothing more
        await body.aclose()
        hold_open.set()
        await asyncio.sleep(0)

        session.expire_all()
        assert await developer_balance(session, developer_id) == Decimal("10")
        assert await escrow_balance(session, developer_id) == 0

    async def test_the_node_is_told_to_stop(self) -> None:
        """A disconnect must reach the node, or a GPU keeps running for nobody.

        Asserted at the relay, which is the only component that can see both ends: the
        coordinator's HTTP stream closing is what ends `Tunnel.stream`, and its `finally`
        is what puts a `cancel` on the wire.
        """
        from app.relay import Tunnel

        sent: list[dict] = []

        class FakeWS:
            async def send_json(self, msg):
                sent.append(msg)

        tunnel = Tunnel(FakeWS())
        stream = tunnel.stream(job_id=None, method="chat.completions", payload={}, timeout=5)

        agen = stream.__aiter__()
        request_id = None

        async def feed():
            nonlocal request_id
            while not sent:
                await asyncio.sleep(0)
            request_id = sent[0]["request_id"]
            await tunnel.handle_incoming({"type": "chunk", "request_id": request_id, "delta": "a"})

        feeder = asyncio.create_task(feed())
        assert (await agen.__anext__())["delta"] == "a"
        await feeder

        await stream.aclose()  # consumer went away mid-generation

        cancels = [m for m in sent if m.get("type") == "cancel"]
        assert cancels == [{"type": "cancel", "request_id": request_id}], (
            "abandoning a stream must cancel it at the node"
        )

    async def test_a_finished_stream_is_not_cancelled(self) -> None:
        """The other direction: a stream that ended normally must NOT send a cancel.

        Without this, the assertion above passes for a tunnel that cancels unconditionally —
        which would tell every node to stop work it had already completed.
        """
        from app.relay import Tunnel

        sent: list[dict] = []

        class FakeWS:
            async def send_json(self, msg):
                sent.append(msg)

        tunnel = Tunnel(FakeWS())
        stream = tunnel.stream(job_id=None, method="chat.completions", payload={}, timeout=5)
        agen = stream.__aiter__()

        async def feed():
            while not sent:
                await asyncio.sleep(0)
            rid = sent[0]["request_id"]
            await tunnel.handle_incoming({"type": "response", "request_id": rid, "status": 200})

        feeder = asyncio.create_task(feed())
        assert (await agen.__anext__())["type"] == "response"
        await feeder
        await stream.aclose()

        assert [m for m in sent if m.get("type") == "cancel"] == []


class TestNodeFailure:
    """A node that dies mid-stream costs the developer nothing."""

    async def test_hold_is_released_in_full(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))

        body = await drive(
            monkeypatch,
            [chunk("a", tokens=1), {"type": "error", "error": "tunnel closed"}],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            worst_case=Decimal("1"),
        )
        events = data_events([f async for f in body])

        assert events[-1] == "[DONE]"
        assert any(isinstance(e, dict) and "error" in e for e in events)

        session.expire_all()
        assert await developer_balance(session, developer_id) == Decimal("10"), "charged anyway"
        assert await escrow_balance(session, developer_id) == 0

    async def test_a_failure_status_on_the_terminal_frame_also_releases(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        """The node's own error reply, not a relay-synthesised one."""
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))

        body = await drive(
            monkeypatch,
            [chunk("a"), {"type": "response", "status": 502, "payload": {"error": "ollama"}}],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            worst_case=Decimal("1"),
        )
        [f async for f in body]

        session.expire_all()
        assert await developer_balance(session, developer_id) == Decimal("10")
        assert await escrow_balance(session, developer_id) == 0


class TestHostileFrames:
    """A node chooses these bytes. None of them may 500 the coordinator."""

    @pytest.mark.parametrize(
        "bad",
        [
            {"type": "chunk", "delta": None},
            {"type": "chunk", "delta": 123},
            {"type": "chunk", "delta": {"nested": "object"}},
            {"type": "chunk"},
            {"type": "unknown-frame-type"},
            {"type": "chunk", "delta": "", "tokens": 5},
        ],
    )
    async def test_a_malformed_chunk_does_not_break_the_stream(
        self, client: AsyncClient, session, monkeypatch, bad
    ) -> None:
        """Not merely "no 500": the junk must not reach the client or the invoice.

        Asserting only that the stream survives is too weak — passing the bad value straight
        through would also survive, while emitting `{"content": null}` to a client that
        expects a string and counting a non-token as a token on the bill.
        """
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))

        body = await drive(
            monkeypatch,
            [bad, chunk("real"), terminal(completion=1)],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            worst_case=Decimal("1"),
        )
        events = data_events([f async for f in body])

        assert events[-1] == "[DONE]"
        # Every content delta the client sees is a string. A malformed frame is dropped,
        # never forwarded.
        contents = [
            c["delta"]["content"]
            for e in events[:-1]
            if isinstance(e, dict)
            for c in e.get("choices", [])
            if "content" in c.get("delta", {})
        ]
        assert contents == ["real"], f"a malformed frame reached the client: {contents}"

        session.expire_all()
        assert await escrow_balance(session, developer_id) == 0

    @pytest.mark.parametrize("tokens", ["lots", True, -5, None, [1]])
    async def test_an_unusable_token_count_falls_back_instead_of_dropping_the_text(
        self, client: AsyncClient, session, monkeypatch, tokens
    ) -> None:
        """A junk `tokens` field costs the node its count, not its chunk.

        The delta is valid text the developer asked for, so it is delivered; only the
        unusable count is discarded, and the coordinator falls back to counting frames. The
        opposite — dropping the text because a sibling field was malformed — would let one
        bad field silently truncate a reply.
        """
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))

        body = await drive(
            monkeypatch,
            [{"type": "chunk", "delta": "ok", "tokens": tokens}, terminal(completion=1)],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            worst_case=Decimal("1"),
        )
        events = data_events([f async for f in body])

        contents = [
            c["delta"]["content"]
            for e in events[:-1]
            if isinstance(e, dict)
            for c in e.get("choices", [])
            if "content" in c.get("delta", {})
        ]
        assert contents == ["ok"]
        session.expire_all()
        assert await escrow_balance(session, developer_id) == 0

    async def test_an_unknown_frame_type_does_not_truncate_the_stream(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        """Only `response` ends a stream successfully.

        An unrecognised frame used to fall through to the terminal-success branch, so a node
        could stop early and still be paid for what it had emitted — its own reply, cut
        short, at no cost to itself. Everything after the junk frame must still arrive.
        """
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))

        body = await drive(
            monkeypatch,
            [chunk("a"), {"type": "surprise"}, chunk("b"), terminal(completion=2)],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            worst_case=Decimal("1"),
        )
        events = data_events([f async for f in body])

        contents = [
            c["delta"]["content"]
            for e in events[:-1]
            if isinstance(e, dict)
            for c in e.get("choices", [])
            if "content" in c.get("delta", {})
        ]
        assert contents == ["a", "b"], "an unknown frame truncated the stream"

    async def test_a_node_cannot_bill_past_the_ceiling_by_inflating_tokens(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        """The clamp the unary path applies has to hold on the streamed path too.

        The node reports the count it is paid from, so an unclamped one is simply a number
        the provider chooses for its own invoice.
        """
        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))

        body = await drive(
            monkeypatch,
            [chunk("a", tokens=10**9), terminal(prompt=10, completion=10**9)],
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            worst_case=Decimal("1"),
            max_output=50,
        )
        events = data_events([f async for f in body])

        usage_event = next(e for e in events[:-1] if isinstance(e, dict) and "usage" in e)
        assert usage_event["usage"]["completion_tokens"] == 50, "ceiling not enforced"
        # And the MONEY is clamped, not just the number shown. 10 in @ 0.05/Mtok +
        # 50 out @ 0.08/Mtok = 0.0000045 -> 0.000005 quantised. Billing the claim instead
        # would have charged ~80 USDC on a 1 USDC hold.
        assert Decimal(usage_event["cost_usdc"]) == Decimal("0.000005")

        session.expire_all()
        charged = Decimal("10") - await developer_balance(session, developer_id)
        assert charged == Decimal("0.000005"), "the ledger was charged the node's claim"


class TestUnaryIsUnaffected:
    """stream=false must behave exactly as before — the streamed path is additive."""

    async def test_the_unary_route_still_returns_json(self, client: AsyncClient, session) -> None:
        from unittest.mock import AsyncMock, patch

        from conftest import auth

        dev_id, key = await register(client, "developer", "Acme")
        await credit_deposit(session, developer_id=uuid.UUID(dev_id), amount=Decimal("10"))
        await session.commit()
        await make_node(session)

        reply = {
            "status": 200,
            "payload": {
                "content": "hello",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        }
        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=reply)):
            res = await client.post(
                "/v1/chat/completions",
                headers=auth(key),
                json={
                    "model": CHAT_MODEL,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                },
            )

        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("application/json")
        assert res.json()["choices"][0]["message"]["content"] == "hello"


class TestRelayStreamProtocol:
    """The relay half: buffering bounds, tunnel death, and not breaking the unary path."""

    @staticmethod
    def _tunnel():
        from app.relay import Tunnel

        sent: list[dict] = []

        class FakeWS:
            async def send_json(self, msg):
                sent.append(msg)

        return Tunnel(FakeWS()), sent

    async def test_a_flooding_node_cannot_grow_the_relay_without_limit(self) -> None:
        """The frame-count bound, which the 1 MiB per-frame cap does not provide.

        A node that generates faster than the coordinator reads would otherwise queue frames
        forever. The stream is ended rather than trimmed: silently dropping chunks would
        under-report the tokens the request is billed on.
        """
        from app.relay import _MAX_STREAM_QUEUE_FRAMES

        tunnel, sent = self._tunnel()
        stream = tunnel.stream(job_id=None, method="chat.completions", payload={}, timeout=5)
        agen = stream.__aiter__()

        # Start the request without consuming, so everything backs up in the queue.
        pump = asyncio.create_task(agen.__anext__())
        while not sent:
            await asyncio.sleep(0)
        rid = sent[0]["request_id"]

        for i in range(_MAX_STREAM_QUEUE_FRAMES + 50):
            await tunnel.handle_incoming(
                {"type": "chunk", "request_id": rid, "delta": "x", "tokens": i}
            )

        frames = [await pump]
        while frames[-1].get("type") == "chunk":
            frames.append(await agen.__anext__())

        assert frames[-1]["type"] == "error"
        assert "buffer" in frames[-1]["error"]
        assert len(frames) <= _MAX_STREAM_QUEUE_FRAMES + 1, "the queue grew past its bound"
        await stream.aclose()

    async def test_a_dropped_tunnel_ends_the_stream_promptly(self) -> None:
        """`fail_all` has to reach streams, not just the unary futures.

        A stream is parked on a queue read, not a future, so an exception cannot be set on
        it. Without an explicit terminal frame the consumer would sit out the whole
        inter-frame timeout on a socket that is already gone.
        """
        from app.relay import TunnelClosedError

        tunnel, sent = self._tunnel()
        stream = tunnel.stream(job_id=None, method="chat.completions", payload={}, timeout=30)
        agen = stream.__aiter__()

        pump = asyncio.create_task(agen.__anext__())
        while not sent:
            await asyncio.sleep(0)

        tunnel.fail_all(TunnelClosedError("tunnel closed"))
        frame = await asyncio.wait_for(pump, timeout=1)

        assert frame["type"] == "error"
        assert "closed" in frame["error"]
        await stream.aclose()

    async def test_the_unary_correlation_still_works(self) -> None:
        """A `response` for a non-streamed request still resolves its future.

        The receive loop now checks the stream registry first; a bug there would break
        every unary dispatch while every streaming test stayed green.
        """
        tunnel, sent = self._tunnel()
        call = asyncio.create_task(
            tunnel.call(job_id=None, method="chat.completions", payload={}, timeout=5)
        )
        while not sent:
            await asyncio.sleep(0)
        rid = sent[0]["request_id"]
        assert sent[0]["stream"] is False

        await tunnel.handle_incoming(
            {"type": "response", "request_id": rid, "status": 200, "payload": {"content": "hi"}}
        )
        reply = await asyncio.wait_for(call, timeout=1)
        assert reply["payload"]["content"] == "hi"

    async def test_a_late_chunk_for_a_finished_stream_is_ignored(self) -> None:
        """Frames arriving after a stream is deregistered must not resolve anything.

        A cancelled stream's node may still have chunks in flight; they have nowhere to go
        and must not be mistaken for a unary reply.
        """
        tunnel, sent = self._tunnel()
        stream = tunnel.stream(job_id=None, method="chat.completions", payload={}, timeout=5)
        agen = stream.__aiter__()
        pump = asyncio.create_task(agen.__anext__())
        while not sent:
            await asyncio.sleep(0)
        rid = sent[0]["request_id"]
        await tunnel.handle_incoming({"type": "response", "request_id": rid, "status": 200})
        await pump
        await stream.aclose()

        # No exception, no state change — the frame simply has nowhere to go.
        await tunnel.handle_incoming({"type": "chunk", "request_id": rid, "delta": "late"})


class TestDispatchNeverStarts:
    """The relay is down or the node vanished between selection and dispatch."""

    async def test_the_hold_is_released_and_the_stream_terminates_cleanly(
        self, client: AsyncClient, session, monkeypatch
    ) -> None:
        """A failure before the first frame still owes the client a well-formed ending.

        The role delta has already gone out by the time dispatch fails, so the response is
        committed; raising here would drop the connection and leave the client to infer the
        outcome from a stream that merely stops. Every failure path ends the same way
        instead — error event, then `[DONE]`.
        """
        from app.dispatch import DispatchError

        developer_id, provider_id = await setup_funded(client, session)
        held = await reserve_balance(session, developer_id=developer_id, amount=Decimal("1"))

        async def boom(provider_id, *, method, payload, settings, job_id=None):
            raise DispatchError("relay unreachable")
            yield  # pragma: no cover - makes this an async generator

        monkeypatch.setattr("app.streaming_chat.dispatch_stream", boom)

        from app.config import get_settings

        body = chat_stream_body(
            spec=get_model(CHAT_MODEL),
            model=CHAT_MODEL,
            payload={"model": CHAT_MODEL, "messages": []},
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            worst_case=Decimal("1"),
            prompt_tokens=10,
            max_output=100,
            created=0,
            settings=get_settings(),
        )
        events = data_events([f async for f in body])

        assert events[-1] == "[DONE]"
        assert any(isinstance(e, dict) and "error" in e for e in events)
        assert not any(isinstance(e, dict) and "usage" in e for e in events)

        session.expire_all()
        assert await developer_balance(session, developer_id) == Decimal("10"), "charged anyway"
        assert await escrow_balance(session, developer_id) == 0
