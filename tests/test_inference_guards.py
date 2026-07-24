"""The three guards that stand between a developer's balance and a wrong number.

1. Short balance → refused BEFORE a node is touched. A request that cannot be paid for
   must never burn a provider's GPU.
2. A failed request → not charged. There is no hold to strand and no refund to forget,
   so "not charged" has to mean the ledger never moved.
3. A completed request → billed at most what the gate approved. The node reports the
   tokens it used and is paid from that report, so the report is a claim by an
   interested party, not a fact.

All are mutation-tested: the guard is removed and the test must go red. A guard whose
test passes without it is decoration.
"""

import base64
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.config import get_settings
from app.dispatch import inflight_count, reset_inflight, select_node, track_inflight
from app.ledger import deposit_stake
from app.models import Provider, ProviderModel
from app.schemas import ChatCompletionRequest
from app.usage_billing import (
    InsufficientBalanceError,
    charge_usage,
    credit_deposit,
    developer_balance,
    quantize_usdc,
)
from conftest import auth, register, wallet_address
from httpx import AsyncClient

CHAT_MODEL = "llama-3.1-8b"


@pytest.fixture(autouse=True)
def _clean_inflight():
    reset_inflight()
    yield
    reset_inflight()


async def make_node(session, *, models=(CHAT_MODEL,), stake=1000) -> Provider:
    now = datetime.now(UTC)
    p = Provider(
        name=f"node-{uuid.uuid4().hex[:6]}",
        last_seen=now,
        connected_at=now,
        wallet_address=wallet_address(),
    )
    session.add(p)
    await session.flush()
    session.add_all(ProviderModel(provider_id=p.id, model=m) for m in models)
    if stake:
        await deposit_stake(session, p.id, Decimal(stake))
    await session.commit()
    return p


async def fund(session, dev: uuid.UUID, amount: str) -> None:
    await credit_deposit(session, developer_id=dev, amount=Decimal(amount))
    await session.commit()


async def chat(client: AsyncClient, key: str, **over):
    body = {"model": CHAT_MODEL, "messages": [{"role": "user", "content": "hi"}], **over}
    return await client.post("/v1/chat/completions", headers=auth(key), json=body)


# ── Guard 1: the balance gate fires before dispatch ──────────────────────────────


class TestBalanceGate:
    async def test_an_empty_balance_is_refused_before_the_node_is_touched(
        self, client: AsyncClient, session
    ) -> None:
        _, key = await register(client, "developer", "Broke")
        await make_node(session)

        call = AsyncMock()
        with patch("app.dispatch.call_provider", new=call):
            res = await chat(client, key, max_tokens=1000)

        assert res.status_code == 402
        call.assert_not_awaited()  # the GPU was never asked to do anything

    async def test_a_balance_below_the_worst_case_is_refused(
        self, client: AsyncClient, session
    ) -> None:
        """Gated on the ceiling, not a guess: 1000 output tokens at 0.08/Mtok."""
        dev_id, key = await register(client, "developer", "Thin")
        await fund(session, uuid.UUID(dev_id), "0.00001")
        await make_node(session)

        call = AsyncMock()
        with patch("app.dispatch.call_provider", new=call):
            res = await chat(client, key, max_tokens=1000)

        assert res.status_code == 402
        call.assert_not_awaited()

    async def test_a_sufficient_balance_passes_the_gate(self, client: AsyncClient, session) -> None:
        """The other direction: the gate must not refuse a developer who can pay."""
        dev_id, key = await register(client, "developer", "Funded")
        await fund(session, uuid.UUID(dev_id), "1")
        await make_node(session)

        reply = {
            "status": 200,
            "payload": {"content": "hi", "usage": {"prompt_tokens": 5, "completion_tokens": 5}},
        }
        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=reply)):
            res = await chat(client, key, max_tokens=1000)

        assert res.status_code == 200, res.text

    async def test_the_402_says_how_short_they_are(self, client: AsyncClient, session) -> None:
        dev_id, key = await register(client, "developer", "Thin")
        await fund(session, uuid.UUID(dev_id), "0.00001")
        await make_node(session)
        res = await chat(client, key, max_tokens=1000)
        assert "0.00001" in res.text and "USDC" in res.text


# ── Guard 2: failed work is never charged ────────────────────────────────────────


class TestFailedWorkIsFree:
    @pytest.mark.parametrize(
        "failure",
        [
            {"status": 500, "payload": {"detail": "cuda oom"}},
            {"status": 504, "payload": {}},
        ],
    )
    async def test_a_node_error_leaves_the_balance_untouched(
        self, client: AsyncClient, session, failure: dict
    ) -> None:
        dev_id, key = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        await make_node(session)

        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=failure)):
            res = await chat(client, key)

        assert res.status_code == 502
        session.expire_all()
        assert await developer_balance(session, dev) == Decimal("10")

    async def test_a_failed_request_never_reaches_the_charge(
        self, client: AsyncClient, session
    ) -> None:
        """Asserts the ordering directly, because the balance alone cannot.

        get_session rolls back on any exception, so a route that charged and *then* raised
        would still leave the balance intact — every balance assertion above passes even
        with the guard removed. The claim is that billing is never reached for work that
        failed, and only a spy can see that.

        With the pre-dispatch hold, a failed request must do exactly one thing to the
        reservation: return it. So the spy checks both directions — the charge (settle) is
        never reached, and the hold IS released, so nothing is stranded in escrow.
        """
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session)

        with (
            patch(
                "app.dispatch.call_provider",
                new=AsyncMock(return_value={"status": 500, "payload": {}}),
            ),
            patch("app.routes.inference.settle_reservation", new=AsyncMock()) as settle,
            patch("app.routes.inference.release_reservation", new=AsyncMock()) as release,
        ):
            res = await chat(client, key)

        assert res.status_code == 502
        settle.assert_not_awaited()  # a failed request is never billed
        release.assert_awaited_once()  # and its hold is returned, not stranded

    async def test_a_successful_request_does_reach_the_charge(
        self, client: AsyncClient, session
    ) -> None:
        """The other direction — or the test above would pass on a route that never bills.

        Success settles the reservation (bills) and does NOT release it.
        """
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session)

        reply = {
            "status": 200,
            "payload": {"content": "hi", "usage": {"prompt_tokens": 5, "completion_tokens": 5}},
        }
        with (
            patch("app.dispatch.call_provider", new=AsyncMock(return_value=reply)),
            patch(
                "app.routes.inference.settle_reservation",
                new=AsyncMock(return_value=Decimal("0.001")),
            ) as settle,
            patch("app.routes.inference.release_reservation", new=AsyncMock()) as release,
        ):
            res = await chat(client, key)

        assert res.status_code == 200
        settle.assert_awaited_once()
        release.assert_not_awaited()

    async def test_an_unreachable_node_leaves_the_balance_untouched(
        self, client: AsyncClient, session
    ) -> None:
        from app.relay_client import RelayUnavailableError

        dev_id, key = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        await make_node(session)

        with patch(
            "app.dispatch.call_provider",
            new=AsyncMock(side_effect=RelayUnavailableError("provider not connected")),
        ):
            res = await chat(client, key)

        assert res.status_code == 502
        session.expire_all()
        assert await developer_balance(session, dev) == Decimal("10")

    async def test_a_timed_out_node_is_a_clean_504_and_costs_nothing(
        self, client: AsyncClient, session
    ) -> None:
        """504, not 502: the work may still be running on the node, and the caller should
        know the difference between 'it failed' and 'it never answered'."""
        dev_id, key = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        await make_node(session)

        with patch("app.dispatch.call_provider", new=AsyncMock(side_effect=TimeoutError())):
            res = await chat(client, key)

        assert res.status_code == 504
        session.expire_all()
        assert await developer_balance(session, dev) == Decimal("10")

    async def test_a_relay_gateway_timeout_is_also_a_504(
        self, client: AsyncClient, session
    ) -> None:
        """The real shape: call_provider raise_for_status()es outside its own try, so the
        relay's 504 arrives as an httpx error rather than RelayUnavailableError."""
        import httpx

        dev_id, key = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        await make_node(session)

        exc = httpx.HTTPStatusError(
            "gateway timeout",
            request=httpx.Request("POST", "http://relay/x"),
            response=httpx.Response(504),
        )
        with patch("app.dispatch.call_provider", new=AsyncMock(side_effect=exc)):
            res = await chat(client, key)

        assert res.status_code == 504
        session.expire_all()
        assert await developer_balance(session, dev) == Decimal("10")


# ── Guard 3: the bill never exceeds the ceiling the gate approved ────────────────


class TestTheCeilingIsReal:
    """The gate prices the worst case and checks the balance against it. That promise is
    only worth something if the bill is actually bounded by it.

    The node is not a neutral narrator here: it reports the token counts, and it is paid
    from those counts. Every other defence in the system — canary, reputation, staking —
    exists because a provider can lie. Billing is the one place where a lie is a direct
    transfer from the developer's balance to the liar's.
    """

    def _reply(self, *, prompt: int, completion: int) -> dict:
        return {
            "status": 200,
            "payload": {
                "content": "hi",
                "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
            },
        }

    async def test_a_node_inflating_its_usage_cannot_bill_past_the_ceiling(
        self, client: AsyncClient, session
    ) -> None:
        """A hostile node claims a million tokens each way on a 100-token request.

        Gated: 1 prompt token @ 0.05/Mtok + 100 output @ 0.08/Mtok = 0.00000805 → 0.000008.
        Believed, the claim would bill 0.05 + 0.08 = 0.13 — sixteen thousand times the
        ceiling the developer's balance was actually checked against.
        """
        dev_id, key = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        await make_node(session)

        with patch(
            "app.dispatch.call_provider",
            new=AsyncMock(return_value=self._reply(prompt=1_000_000, completion=1_000_000)),
        ):
            res = await chat(client, key, max_tokens=100)

        assert res.status_code == 200, res.text
        assert Decimal(res.json()["cost_usdc"]) == Decimal("0.000008")
        session.expire_all()
        assert await developer_balance(session, dev) == Decimal("9.999992")

    async def test_the_reported_usage_cannot_exceed_the_ceiling_either(
        self, client: AsyncClient, session
    ) -> None:
        """The bill and the receipt have to agree.

        Clamping the charge but echoing the node's fiction back would hand the developer a
        receipt for a million tokens next to a bill for a hundred, and leave the same lie
        in whatever reads usage next.
        """
        dev_id, key = await register(client, "developer", "Acme")
        await fund(session, uuid.UUID(dev_id), "10")
        await make_node(session)

        with patch(
            "app.dispatch.call_provider",
            new=AsyncMock(return_value=self._reply(prompt=8, completion=1_000_000)),
        ):
            res = await chat(client, key, max_tokens=100)

        assert res.json()["usage"]["completion_tokens"] == 100

    async def test_an_honest_node_is_still_paid_for_what_it_actually_did(
        self, client: AsyncClient, session
    ) -> None:
        """The other direction, and the one that makes the guard a clamp rather than a
        flat rate: a node that used 50 of its 100 allowed tokens bills for 50.

        Without this, 'always charge the ceiling' would pass the test above while
        overcharging every honest request on the network.
        """
        dev_id, key = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        await make_node(session)

        with patch(
            "app.dispatch.call_provider",
            new=AsyncMock(return_value=self._reply(prompt=1, completion=50)),
        ):
            res = await chat(client, key, max_tokens=100)

        # 1 in @ 0.05/Mtok + 50 out @ 0.08/Mtok = 0.00000405 → 0.000004.
        assert Decimal(res.json()["cost_usdc"]) == Decimal("0.000004")
        assert res.json()["usage"]["completion_tokens"] == 50
        session.expire_all()
        assert await developer_balance(session, dev) == Decimal("9.999996")

    async def test_a_node_cannot_bill_for_more_images_than_were_asked_for(
        self, client: AsyncClient, session
    ) -> None:
        """The image path bills per image returned, which lets the node choose the count.

        Asked for one, sent five: the developer pays for one. The gate priced one, and
        nobody agreed to buy the other four.
        """
        dev_id, key = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        await make_node(session, models=("sdxl-turbo",))

        images = [base64.b64encode(b"\x89PNG\r\n" + bytes([i])).decode("ascii") for i in range(5)]
        reply = {"status": 200, "payload": {"images": images}}
        with patch("app.dispatch.call_provider", new=AsyncMock(return_value=reply)):
            res = await client.post(
                "/v1/images/generations",
                headers=auth(key),
                json={"model": "sdxl-turbo", "prompt": "a cat", "n": 1},
            )

        assert res.status_code == 200, res.text
        assert Decimal(res.json()["cost_usdc"]) == Decimal("0.01")
        assert len(res.json()["data"]) == 1
        session.expire_all()
        assert await developer_balance(session, dev) == Decimal("9.99")


# ── Guard 3b: the prompt bound is a true upper bound (bytes, not characters) ──────


class TestTheBoundIsBytesNotChars:
    """`_prompt_token_bound` sizes both the gate and the bill ceiling, so it must never
    fall below a node's real token count — or the ceiling clamps an honest node's bill down.

    Counting characters looked like an upper bound but is not: the byte-level BPE these
    models use can turn one character into several tokens (an emoji, a ZWJ-joined grapheme),
    so a character count can sit *below* the true token count. UTF-8 byte length can't —
    every token maps to at least one byte, so byte_count >= token_count always.
    """

    def _reply(self, *, prompt: int, completion: int) -> dict:
        return {
            "status": 200,
            "payload": {
                "content": "hi",
                "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
            },
        }

    def test_the_bound_counts_utf8_bytes_not_characters(self) -> None:
        """A direct read of the bound. A ZWJ family emoji is 7 Python characters but 25
        UTF-8 bytes, and a byte-level tokeniser produces several tokens for it — all above 7.
        The bound must report the bytes to stay above the token count.

        Mutation guard: revert the body to `len(m.content)` and this drops to 7 — red.
        """
        from app.routes.inference import _prompt_token_bound

        body = ChatCompletionRequest(
            model=CHAT_MODEL, messages=[{"role": "user", "content": "👨‍👩‍👧‍👦"}]
        )
        assert _prompt_token_bound(body) == 25  # bytes, not 7 characters

    def test_ascii_is_unchanged_from_the_character_count(self) -> None:
        """The trade-off is one-sided: for ASCII, one byte per character, so English prompts
        get the exact same bound they had under the character count — no regression."""
        from app.routes.inference import _prompt_token_bound

        body = ChatCompletionRequest(
            model=CHAT_MODEL, messages=[{"role": "user", "content": "hello world"}]
        )
        assert _prompt_token_bound(body) == len("hello world") == 11

    async def test_an_honest_node_on_emoji_is_paid_above_the_character_count(
        self, client: AsyncClient, session
    ) -> None:
        """The underpay bug the byte bound fixes, end to end.

        Prompt: a family emoji ×20 = 140 characters, 500 UTF-8 bytes. An honest byte-level
        node reports 300 prompt tokens — more than the 140 characters, fewer than the 500
        bytes: exactly the range a character bound gets wrong.

        Cost of what the node did: 300 in @ 0.05/Mtok + 1 out @ 0.08/Mtok = 0.00001508.
          - byte ceiling (input 500): 0.00002508 — does not bind; node is paid 0.000015.
          - char ceiling (input 140): 0.00000708 — WOULD clamp the bill to 0.000007,
            underpaying the honest node by more than half, silently.

        Mutation guard: revert the bound to characters and the asserted 0.000015 becomes
        0.000007 — red.
        """
        dev_id, key = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        await make_node(session)

        prompt = "👨‍👩‍👧‍👦" * 20
        with patch(
            "app.dispatch.call_provider",
            new=AsyncMock(return_value=self._reply(prompt=300, completion=1)),
        ):
            res = await client.post(
                "/v1/chat/completions",
                headers=auth(key),
                json={
                    "model": CHAT_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1,
                },
            )

        assert res.status_code == 200, res.text
        # Paid for what it reported, not clamped down to the character ceiling.
        assert Decimal(res.json()["cost_usdc"]) == Decimal("0.000015")
        assert res.json()["usage"]["prompt_tokens"] == 300
        session.expire_all()
        assert await developer_balance(session, dev) == Decimal("9.999985")

    async def test_a_cjk_prompt_over_states_the_ceiling_without_overcharging(
        self, client: AsyncClient, session
    ) -> None:
        """The documented CJK trade-off, verified harmless to the bill.

        Prompt: a CJK character ×100 = 100 characters, 300 UTF-8 bytes (~3×). The byte bound
        over-states the ceiling — loose, and on the developer's side — but an honest node
        reporting ~1 token/character (100 tokens) is billed for exactly that, because the
        generous ceiling does not bind: 100 in @ 0.05/Mtok + 1 out @ 0.08/Mtok = 0.00000508.
        A looser ceiling is a `max`, so it can never turn into an overcharge; the bill still
        tracks the node's real usage.
        """
        dev_id, key = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        await make_node(session)

        prompt = "中" * 100
        with patch(
            "app.dispatch.call_provider",
            new=AsyncMock(return_value=self._reply(prompt=100, completion=1)),
        ):
            res = await client.post(
                "/v1/chat/completions",
                headers=auth(key),
                json={
                    "model": CHAT_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1,
                },
            )

        assert res.status_code == 200, res.text
        assert Decimal(res.json()["cost_usdc"]) == Decimal("0.000005")
        session.expire_all()
        assert await developer_balance(session, dev) == Decimal("9.999995")


# ── The charge itself ────────────────────────────────────────────────────────────


class TestChargeUsage:
    async def test_developer_pays_provider_earns_protocol_takes_its_fee(
        self, client: AsyncClient, session
    ) -> None:
        from app.ledger import account_balance
        from app.models import LedgerAccount

        dev_id, _ = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        node = await make_node(session)

        cost = await charge_usage(
            session,
            developer_id=dev,
            provider_id=node.id,
            cost=Decimal("1.00"),
            settings=get_settings(),
        )
        await session.commit()

        assert cost == Decimal("1.00")
        assert await developer_balance(session, dev) == Decimal("9.00")
        # 250 bps of 1.00 = 0.025 to the protocol; the provider gets the remainder.
        assert await account_balance(session, LedgerAccount.provider, node.id) == Decimal("0.975")

    async def test_the_legs_always_net_to_zero(self, client: AsyncClient, session) -> None:
        """The ledger's one invariant, checked on an amount whose fee cannot divide evenly."""
        from app.ledger import verify_ledger_integrity

        dev_id, _ = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        node = await make_node(session)

        await charge_usage(
            session,
            developer_id=dev,
            provider_id=node.id,
            cost=Decimal("0.000333"),
            settings=get_settings(),
        )
        await session.commit()
        # An empty list is zero discrepancy: every entry_group's debits equal its credits.
        assert await verify_ledger_integrity(session) == []

    async def test_charging_more_than_the_balance_raises(
        self, client: AsyncClient, session
    ) -> None:
        dev_id, _ = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "1")
        node = await make_node(session)

        with pytest.raises(InsufficientBalanceError):
            await charge_usage(
                session,
                developer_id=dev,
                provider_id=node.id,
                cost=Decimal("2"),
                settings=get_settings(),
            )

    async def test_a_zero_cost_request_posts_nothing(self, client: AsyncClient, session) -> None:
        dev_id, _ = await register(client, "developer", "Acme")
        dev = uuid.UUID(dev_id)
        await fund(session, dev, "10")
        node = await make_node(session)

        assert await charge_usage(
            session, developer_id=dev, provider_id=node.id, cost=Decimal(0), settings=get_settings()
        ) == Decimal(0)
        assert await developer_balance(session, dev) == Decimal("10")

    def test_amounts_are_quantised_to_usdc_six_decimals(self) -> None:
        """The number in the UI must equal the number a contract would move."""
        assert quantize_usdc(Decimal("0.0000005")) == Decimal("0.000001")
        assert quantize_usdc(Decimal("1.23456789")) == Decimal("1.234568")


# ── Least-loaded selection uses real inflight, not a constant ────────────────────


class TestLeastLoaded:
    async def test_a_busy_node_is_passed_over_for_an_idle_one(self, session) -> None:
        busy = await make_node(session)
        idle = await make_node(session)

        with track_inflight(busy.id):
            chosen = await select_node(
                session, model=CHAT_MODEL, now=datetime.now(UTC), settings=get_settings()
            )
        assert chosen == idle.id

    async def test_load_is_released_when_the_request_finishes(self, session) -> None:
        node = await make_node(session)
        with track_inflight(node.id):
            assert inflight_count(node.id) == 1
        assert inflight_count(node.id) == 0

    async def test_load_is_released_even_when_the_request_explodes(self, session) -> None:
        """A node that errors must not look busy forever, or one bad request retires it."""
        node = await make_node(session)
        with pytest.raises(RuntimeError), track_inflight(node.id):
            raise RuntimeError("node blew up")
        assert inflight_count(node.id) == 0

    async def test_dispatch_counts_the_request_while_it_is_out(self, session) -> None:
        """Proves the counter tracks real dispatches, not just the helper."""
        from app.dispatch import dispatch

        node = await make_node(session)
        seen = {}

        async def _slow(*_a, **_kw):
            seen["during"] = inflight_count(node.id)
            return {"status": 200, "payload": {}}

        with patch("app.dispatch.call_provider", new=_slow):
            await dispatch(node.id, method="chat.completions", payload={}, settings=get_settings())

        assert seen["during"] == 1
        assert inflight_count(node.id) == 0
