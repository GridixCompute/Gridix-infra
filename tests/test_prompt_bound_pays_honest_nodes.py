"""The prompt-token number bounds the bill, so understating it underpays the provider.

It does two jobs: it sizes the pre-dispatch gate, and it sizes the ceiling that caps what a
node can be paid. A guess that is too low quietly cuts an honest node's bill, and the node
has no way to see it happening — it just earns less than it should and eventually leaves.

The old ratio was chars//4, fair for English prose and about 4x low for CJK.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.catalog import chat_cost, get_model
from app.usage_billing import developer_balance, quantize_usdc
from conftest import auth, register
from httpx import AsyncClient

from tests.test_inference import fund, make_node

pytestmark = pytest.mark.anyio

MAX_OUT = 512


async def _run(client: AsyncClient, session, prompt: str, real_prompt_tokens: int):
    dev_id, key = await register(client, "developer", "Acme")
    await fund(session, uuid.UUID(dev_id), "10")
    await make_node(session)
    dev = uuid.UUID(dev_id)

    before = await developer_balance(session, dev)
    reply = {
        "status": 200,
        "payload": {
            "content": "ok",
            "usage": {"prompt_tokens": real_prompt_tokens, "completion_tokens": MAX_OUT},
        },
    }
    with patch("app.dispatch.call_provider", new=AsyncMock(return_value=reply)):
        res = await client.post(
            "/v1/chat/completions",
            headers=auth(key),
            json={
                "model": "llama-3.1-8b",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": MAX_OUT,
            },
        )
    assert res.status_code == 200, res.text
    session.expire_all()
    return before - await developer_balance(session, dev)


@pytest.mark.parametrize(
    ("prompt", "real_tokens", "label"),
    [
        pytest.param("文" * 400, 400, "CJK: ~1 token per character", id="cjk"),
        pytest.param("🙂" * 200, 200, "emoji", id="emoji"),
        pytest.param("a" * 400, 100, "English prose: ~4 chars per token", id="english"),
    ],
)
async def test_an_honest_node_is_paid_what_it_earned(
    client: AsyncClient, session, prompt, real_tokens, label
):
    spec = get_model("llama-3.1-8b")
    earned = chat_cost(spec, input_tokens=real_tokens, output_tokens=MAX_OUT)
    charged = await _run(client, session, prompt, real_tokens)
    assert charged >= earned, (
        f"{label}: node read {real_tokens} tokens and wrote {MAX_OUT}; earned {earned} but "
        f"was paid {charged} — short by {earned - charged}"
    )


async def test_a_lying_node_is_still_capped(client: AsyncClient, session):
    """The bound must not become a licence to invent prompt tokens.

    Without this, 'pay honest nodes more' passes trivially by removing the cap.
    """
    spec = get_model("llama-3.1-8b")
    prompt = "a" * 400
    # Node claims 100x the prompt it was sent.
    charged = await _run(client, session, prompt, 40_000)
    # Quantised, because the charge is. The ceiling is raw arithmetic and USDC has six
    # decimals, so what a caller can actually be billed is the ceiling rounded to a payable
    # number — which can sit a sliver above the raw value, under half a millionth of a USDC.
    ceiling = quantize_usdc(chat_cost(spec, input_tokens=len(prompt), output_tokens=MAX_OUT))
    assert charged <= ceiling, (
        f"node claimed 40000 prompt tokens on a {len(prompt)}-character prompt and was paid "
        f"{charged} > {ceiling}"
    )
