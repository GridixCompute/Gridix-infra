"""What the gate approves is what the bill may not exceed.

The gate checks the balance against a ceiling, then the same ceiling caps the charge. But
the charge is quantised to USDC's six decimals on the way out, and a ceiling computed from
raw arithmetic is not always a payable number. Price a request at exactly 0.0000005 — the
gate approves that, the charge quantises to 0.000001, and the developer pays double what
they were asked to approve.

llama-3.1-8b at 0.05/0.08 per Mtok: an 8-character prompt (2 tokens by the bound) with
max_tokens=5 lands exactly on 0.0000005.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.catalog import chat_worst_case, get_model
from app.usage_billing import ceil_usdc, developer_balance, quantize_usdc
from conftest import auth, register
from httpx import AsyncClient

from tests.test_inference import fund, make_node, node_reply

pytestmark = pytest.mark.anyio


def test_a_raw_ceiling_is_not_always_payable() -> None:
    """The premise, before spending a request on it."""
    spec = get_model("llama-3.1-8b")
    raw = chat_worst_case(spec, input_tokens=2, max_output_tokens=5)
    assert raw == Decimal("0.0000005")
    assert quantize_usdc(raw) > raw, "this arithmetic no longer lands on a rounding boundary"
    assert ceil_usdc(raw) == Decimal("0.000001")


async def test_the_charge_never_exceeds_what_the_gate_required(client: AsyncClient, session):
    dev_id, key = await register(client, "developer", "Acme")
    await fund(session, uuid.UUID(dev_id), "10")
    await make_node(session)
    dev = uuid.UUID(dev_id)

    spec = get_model("llama-3.1-8b")
    # What the developer's balance is actually checked against.
    gated = ceil_usdc(chat_worst_case(spec, input_tokens=2, max_output_tokens=5))

    before = await developer_balance(session, dev)
    with patch(
        "app.dispatch.call_provider", new=AsyncMock(return_value=node_reply(prompt=2, completion=5))
    ):
        res = await client.post(
            "/v1/chat/completions",
            headers=auth(key),
            json={
                "model": "llama-3.1-8b",
                "messages": [{"role": "user", "content": "12345678"}],
                "max_tokens": 5,
            },
        )
    assert res.status_code == 200, res.text

    session.expire_all()
    charged = before - await developer_balance(session, dev)
    assert charged <= gated, (
        f"charged {charged} for a request the gate approved at {gated} — rounding punched "
        f"through the ceiling by {charged - gated}"
    )


async def test_a_ceiling_is_still_a_ceiling_not_a_price(client: AsyncClient, session):
    """The other direction: rounding the ceiling up must not become 'always bill the ceiling'.

    Without this, the fix above passes trivially by charging everyone the maximum.
    """
    dev_id, key = await register(client, "developer", "Acme")
    await fund(session, uuid.UUID(dev_id), "10")
    await make_node(session)
    dev = uuid.UUID(dev_id)

    spec = get_model("llama-3.1-8b")
    gated = ceil_usdc(chat_worst_case(spec, input_tokens=8, max_output_tokens=4096))

    before = await developer_balance(session, dev)
    # The node used a fraction of its allowance.
    with patch(
        "app.dispatch.call_provider",
        new=AsyncMock(return_value=node_reply(prompt=8, completion=10)),
    ):
        res = await client.post(
            "/v1/chat/completions",
            headers=auth(key),
            json={
                "model": "llama-3.1-8b",
                "messages": [{"role": "user", "content": "12345678"}],
                "max_tokens": 4096,
            },
        )
    assert res.status_code == 200, res.text

    session.expire_all()
    charged = before - await developer_balance(session, dev)
    assert charged < gated, f"billed the ceiling {gated} for a request that used 10 tokens"
