"""Inference endpoints — the product.

The whole flow, in order, and the order is the point:

1. resolve the model (unknown → 404: no price, no service),
2. gate the balance on the WORST case (short → 402, before any node is touched),
3. select a node that serves it under the placement rules,
4. dispatch and wait,
5. charge for what was ACTUALLY used, and never more than step 2 approved.

A request that fails at the node is never charged. That is the difference from the async
path, which escrows up front and must remember to refund: here there is no hold to
strand. Nothing is billed until a node has returned a result.

The second half of step 5 is what makes step 2 mean anything. The node reports the usage
it is paid for, so the report is a claim by an interested party; the worst case is the
only number the developer's balance was ever checked against, and it binds the bill.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from loguru import logger

from app.catalog import CATALOG, Modality, chat_cost, chat_worst_case, get_model, image_cost
from app.deps import DeveloperDep, SessionDep, SettingsDep
from app.dispatch import (
    DispatchError,
    DispatchTimeoutError,
    NoNodeAvailableError,
    dispatch,
    eligible_nodes,
    select_node,
)
from app.models import DataTier
from app.node_usage import usage_from
from app.schemas import (
    ChatChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatUsage,
    GeneratedImage,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ModelInfo,
    ModelsResponse,
)
from app.siwe import utcnow
from app.streaming_chat import chat_stream_body
from app.usage_billing import (
    InsufficientBalanceError,
    release_reservation,
    reserve_balance,
    settle_reservation,
)

router = APIRouter(prefix="/v1", tags=["inference"])


def _node_failed(exc: DispatchError, provider_id: uuid.UUID, what: str) -> HTTPException:
    """Map a dispatch failure to a status that means what it says.

    504 when the node went quiet — the work may still be running and a retry costs real
    time; 502 when it answered with a failure. Either way nothing is billed: the charge
    is downstream of this.
    """
    logger.warning("{} dispatch to {} failed: {}", what, provider_id, exc)
    if isinstance(exc, DispatchTimeoutError):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The node did not respond in time.",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="The node failed to complete the request.",
    )


def _model_or_404(model_id: str, modality: Modality):
    spec = get_model(model_id)
    if spec is None or spec.modality is not modality:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown model {model_id!r}."
        )
    return spec


def _payment_required(exc: InsufficientBalanceError) -> HTTPException:
    """402, with the numbers — a developer who is short should not have to guess by how much."""
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=(
            f"Balance {exc.balance} USDC is below the {exc.required} USDC this request "
            "could cost. Top up to continue."
        ),
    )


async def _pick_node(session, *, model: str, settings, data_tier: DataTier) -> uuid.UUID:
    try:
        return await select_node(
            session, model=model, now=utcnow(), settings=settings, data_tier=data_tier
        )
    except NoNodeAvailableError as exc:
        # 503, not 404: the model exists, nothing is serving it this second.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No node is currently serving {model!r}.",
        ) from exc


@router.get("/models", response_model=ModelsResponse)
async def list_models(
    session: SessionDep, settings: SettingsDep, _: DeveloperDep
) -> ModelsResponse:
    """Catalogue models, each flagged with whether a node is serving it right now.

    Availability is reported rather than filtered: a developer whose model went dark
    should see that it exists and is offline, not watch it vanish from the list.
    """
    now = utcnow()
    models = []
    for spec in CATALOG.values():
        nodes = await eligible_nodes(session, model=spec.id, now=now, settings=settings)
        models.append(
            ModelInfo(
                id=spec.id,
                modality=spec.modality.value,
                available=bool(nodes),
                nodes=len(nodes),
                input_usdc_per_mtok=spec.input_usdc_per_mtok,
                output_usdc_per_mtok=spec.output_usdc_per_mtok,
                usdc_per_image=spec.usdc_per_image,
                context_window=spec.context_window,
            )
        )
    return ModelsResponse(models=models)


@router.post(
    "/chat/completions",
    response_model=ChatCompletionResponse,
    # `stream=true` answers with text/event-stream, not this model, and FastAPI can only
    # infer one. Declaring the other content type here is the same discipline that made the
    # old 501 visible: a client generates types from this spec, so a response the route
    # really returns has to appear in it, or the generated code is confidently wrong.
    responses={
        status.HTTP_200_OK: {
            "description": (
                "A completed chat completion. With `stream=true` the response is instead an "
                "OpenAI-compatible SSE stream of `chat.completion.chunk` events terminated "
                "by `data: [DONE]`, with usage and `cost_usdc` on the final event."
            ),
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ChatCompletionResponse"}
                },
                "text/event-stream": {"schema": {"type": "string"}},
            },
        },
        status.HTTP_501_NOT_IMPLEMENTED: {
            "description": "data_tier=confidential_tee is not supported on the chat path.",
        },
    },
)
async def chat_completions(
    body: ChatCompletionRequest,
    session: SessionDep,
    settings: SettingsDep,
    developer: DeveloperDep,
):
    """Run a chat completion on the network and bill the tokens it used.

    With `stream=true` the reply is an SSE stream of OpenAI `chat.completion.chunk` events.
    The billing invariants do not change with the shape: the worst case is still reserved
    before a node is touched, and the hold is still resolved exactly once — see
    `app.streaming_chat` for what "exactly once" has to survive when the client hangs up
    mid-generation.
    """
    if body.data_tier is DataTier.confidential_tee:
        # Refused before the gate and before a node, for the same reason streaming is: the
        # request asks for something the network cannot deliver on this path. On the chat
        # path `data_tier` only selects an attested node and then sends the prompt down the
        # tunnel in cleartext — no envelope encryption, no attestation-gated key release,
        # none of the enclave confidentiality the confidential_tee tier promises (that
        # machinery exists for jobs, not for /v1/chat/completions). Accepting the tier here
        # would take money for a guarantee we do not enforce, so we refuse it outright
        # rather than serve a weaker thing under its name.
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "data_tier=confidential_tee is not supported on the chat path: enclave "
            "attestation is not enforced here, so the prompt would reach the node in "
            "cleartext. Use data_tier=public (the default) for chat completions.",
        )
    spec = _model_or_404(body.model, Modality.chat)
    max_output = min(body.max_tokens or spec.max_output_tokens, spec.max_output_tokens)
    prompt_tokens = _prompt_token_bound(body)

    # The gate: reserve the most this could cost before a node is touched. The reservation
    # is atomic against concurrent requests (see reserve_balance), so a second request from
    # the same developer that can only afford one is refused HERE, not after its node has
    # already burned a GPU on work that cannot be paid for.
    worst_case = chat_worst_case(spec, input_tokens=prompt_tokens, max_output_tokens=max_output)
    try:
        held = await reserve_balance(session, developer_id=developer.id, amount=worst_case)
    except InsufficientBalanceError as exc:
        raise _payment_required(exc) from exc

    # From here the hold exists, so every exit must either settle it (success) or release it
    # (any failure) — never leave it stranded in escrow. The `finally` guarantees exactly
    # one of the two runs.
    settled = False
    try:
        provider_id = await _pick_node(
            session, model=body.model, settings=settings, data_tier=body.data_tier
        )
        payload = body.model_dump(mode="json", exclude={"data_tier"})
        payload["max_tokens"] = max_output

        if body.stream:
            # Hand the hold to the stream body, which owns it from here: it settles on a
            # session of its own, long after this handler has returned and this one is
            # closed. `settled` is set so the `finally` below does NOT also release it —
            # a double resolution would credit the developer the hold twice.
            settled = True
            return StreamingResponse(
                chat_stream_body(
                    spec=spec,
                    model=body.model,
                    payload=payload,
                    developer_id=developer.id,
                    provider_id=provider_id,
                    held=held,
                    worst_case=worst_case,
                    prompt_tokens=prompt_tokens,
                    max_output=max_output,
                    created=int(utcnow().timestamp()),
                    settings=settings,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
                },
            )

        try:
            reply = await dispatch(
                provider_id, method="chat.completions", payload=payload, settings=settings
            )
        except DispatchError as exc:
            raise _node_failed(exc, provider_id, "chat") from exc

        usage = _usage_from(reply, prompt_tokens=prompt_tokens, max_output_tokens=max_output)
        # The gate reserved `worst_case`, so the bill is clamped to it: a node that
        # over-reports its usage cannot charge past the ceiling the developer was priced
        # against. The clamp holds on the raw Decimals, but the charge is then quantized
        # half-up to USDC's six decimals, so the amount actually posted can land up to 5e-7
        # (half of USDC's 1e-6 tick) ABOVE this raw ceiling. That overshoot is a rounding
        # artifact at the smallest payable USDC unit, not a leak: it is bounded by the
        # resolution and cannot compound, and 5e-7 USDC is below what the chain can even
        # settle. Quantizing with ceil (always rounding up) was tried and reverted — it
        # raised developer bills by 12.5%, far worse than the half-up tick. So the ceiling
        # binds up to USDC's six-decimal resolution, and no further.
        billed = min(
            chat_cost(
                spec, input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens
            ),
            worst_case,
        )
        cost = await settle_reservation(
            session,
            developer_id=developer.id,
            provider_id=provider_id,
            held=held,
            actual=billed,
            settings=settings,
        )
        settled = True
    finally:
        if not settled:
            await release_reservation(session, developer_id=developer.id, held=held)

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(utcnow().timestamp()),
        model=body.model,
        choices=[
            ChatChoice(
                message=ChatCompletionMessage(content=str(reply.get("content", ""))),
                finish_reason=_finish_reason(usage, max_output_tokens=max_output),
            )
        ],
        usage=usage,
        cost_usdc=cost,
        provider_id=provider_id,
    )


def _finish_reason(usage: ChatUsage, *, max_output_tokens: int) -> Literal["stop", "length"]:
    """Why generation ended — derived, because nodes do not report it and clients read it.

    The ceiling we imposed is the only evidence available: a node that used every token it
    was allowed was cut off; anything less stopped on its own. This can be wrong in exactly
    one direction — a reply that happens to end on the limit reads as truncated — which is
    the safe way round, since reporting a truncated answer as complete is what would
    actually mislead a caller.
    """
    return "length" if usage.completion_tokens >= max_output_tokens else "stop"


@router.post("/images/generations", response_model=ImageGenerationResponse)
async def image_generations(
    body: ImageGenerationRequest,
    session: SessionDep,
    settings: SettingsDep,
    developer: DeveloperDep,
) -> ImageGenerationResponse:
    """Generate images on the network and bill per image returned."""
    spec = _model_or_404(body.model, Modality.image)

    # Same pre-dispatch reservation as chat: hold the worst case atomically so a second
    # concurrent request that can only afford one is refused before a node runs.
    worst_case = image_cost(spec, images=body.n)
    try:
        held = await reserve_balance(session, developer_id=developer.id, amount=worst_case)
    except InsufficientBalanceError as exc:
        raise _payment_required(exc) from exc

    settled = False
    try:
        provider_id = await _pick_node(
            session, model=body.model, settings=settings, data_tier=body.data_tier
        )

        try:
            reply = await dispatch(
                provider_id,
                method="images.generations",
                payload=body.model_dump(mode="json", exclude={"data_tier"}),
                settings=settings,
            )
        except DispatchError as exc:
            raise _node_failed(exc, provider_id, "image") from exc

        # Billed on what came back, not what was asked for: a node returning two of three
        # images is paid for two. Capped at what was asked for, because the count is the
        # node's to choose and `n` is what the gate priced — nobody agreed to buy a sixth
        # image on a request for one.
        #
        # The list check is load-bearing, not defensive habit: strings are iterable, so
        # `images: "abc"` iterated into three "images" and was billed as three. A node could
        # return three bytes and be paid for three pictures. Anything that is not a list is
        # not a set of images, so it counts as none and pays nothing.
        raw_images = reply.get("images")
        if raw_images is not None and not isinstance(raw_images, list):
            logger.warning(
                "node returned {} for images, not a list; treating as no images returned",
                type(raw_images).__name__,
            )
            raw_images = None
        returned = [str(u) for u in (raw_images or [])]
        if len(returned) > body.n:
            logger.warning(
                "node returned {} images for a request of {}; keeping {}",
                len(returned),
                body.n,
                body.n,
            )
        images = returned[: body.n]
        cost = await settle_reservation(
            session,
            developer_id=developer.id,
            provider_id=provider_id,
            held=held,
            actual=image_cost(spec, images=len(images)),
            settings=settings,
        )
        settled = True
    finally:
        if not settled:
            await release_reservation(session, developer_id=developer.id, held=held)

    return ImageGenerationResponse(
        created=int(utcnow().timestamp()),
        data=[GeneratedImage(url=u) for u in images],
        model=body.model,
        cost_usdc=cost,
        provider_id=provider_id,
    )


def _prompt_token_bound(body: ChatCompletionRequest) -> int:
    """An UPPER BOUND on the prompt's tokens, without a tokeniser.

    This number does two jobs, and only one of them wants a good guess. It sizes the
    pre-dispatch gate — which must not understate, or a request slips through that the
    balance cannot cover — and it sizes the ceiling that caps the bill, which must not
    understate either, or an honest node is paid less than it earned.

    The bound is the prompt's length in UTF-8 bytes. Every token a real tokeniser produces
    maps to at least one byte — byte-level BPE, which the models here use, builds tokens out
    of byte sequences, so token_count <= byte_count always. Counting characters looked like
    an upper bound but was not: byte-level BPE can split a single character into several
    tokens (an emoji or a ZWJ-joined grapheme like a family emoji is one Python character
    but many bytes and several tokens), so char_count could fall *below* the true token
    count and the clamp would silently underpay an honest node. Bytes never do that.

    The trade-off is honest looseness, always on the developer's side:
      - ASCII/English: one byte per character, so this is identical to the old char count —
        no change for English prompts.
      - CJK: ~3 bytes per character where a tokeniser sees roughly one token per character,
        so the bound over-states by ~3x. That is bounded and safe: it can only make the
        gate ask for more balance or raise the ceiling, never underpay. It costs little in
        practice because output tokens dominate the price of a chat request.

    A real tokeniser is still the right final answer, and would tighten the CJK case. Until
    then this errs toward refusing a request the developer could afford, rather than
    underpaying a provider who has no way to see it happening.
    """
    total_bytes = sum(len(m.content.encode("utf-8")) for m in body.messages)
    return max(1, total_bytes)


# Reading a node's token report lives in `app.node_usage`, shared with the streamed path so
# both clamp the same way. Re-exported under the old name because the unary path reads
# better with it, and `_usage_from` is what the surrounding comments have always called.
_usage_from = usage_from
