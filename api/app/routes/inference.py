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
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
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
from app.models import DataTier, Developer
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatUsage,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ModelInfo,
    ModelsResponse,
)
from app.siwe import utcnow
from app.usage_billing import InsufficientBalanceError, assert_can_afford, charge_usage

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


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    body: ChatCompletionRequest,
    session: SessionDep,
    settings: SettingsDep,
    developer: DeveloperDep,
) -> ChatCompletionResponse:
    """Run a chat completion on the network and bill the tokens it used."""
    if body.stream:
        # Refused before the gate and before a node: nothing is charged for a request the
        # network cannot serve. Streaming needs the relay to forward frames as the node
        # produces them; returning one blocking body to a caller who asked for a stream
        # would answer the request with something that is not what it asked for, and no
        # client could tell.
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "stream=true is not implemented: the network cannot forward partial results "
            "yet. Send stream=false for a single complete response.",
        )
    spec = _model_or_404(body.model, Modality.chat)
    max_output = min(body.max_tokens or spec.max_output_tokens, spec.max_output_tokens)
    prompt_tokens = _estimate_prompt_tokens(body)

    # The gate: the most this could cost, checked before a node is touched.
    worst_case = chat_worst_case(spec, input_tokens=prompt_tokens, max_output_tokens=max_output)
    try:
        await assert_can_afford(session, developer.id, worst_case)
    except InsufficientBalanceError as exc:
        raise _payment_required(exc) from exc

    provider_id = await _pick_node(
        session, model=body.model, settings=settings, data_tier=body.data_tier
    )
    payload = body.model_dump(mode="json", exclude={"data_tier"})
    payload["max_tokens"] = max_output

    try:
        reply = await dispatch(
            provider_id, method="chat.completions", payload=payload, settings=settings
        )
    except DispatchError as exc:
        # Nothing is charged: no result, no bill. There was never a hold to give back.
        raise _node_failed(exc, provider_id, "chat") from exc

    usage = _usage_from(reply, prompt_tokens=prompt_tokens, max_output_tokens=max_output)
    # The gate checked the balance against `worst_case`. Billing above it would mean
    # charging for something the developer was never asked to approve, so the ceiling
    # holds here too — whatever the node says it did.
    billed = min(
        chat_cost(spec, input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens),
        worst_case,
    )
    cost = await _charge(
        session,
        developer=developer,
        provider_id=provider_id,
        cost=billed,
        settings=settings,
    )
    return ChatCompletionResponse(
        model=body.model,
        content=str(reply.get("content", "")),
        usage=usage,
        cost_usdc=cost,
        provider_id=provider_id,
    )


@router.post("/images/generations", response_model=ImageGenerationResponse)
async def image_generations(
    body: ImageGenerationRequest,
    session: SessionDep,
    settings: SettingsDep,
    developer: DeveloperDep,
) -> ImageGenerationResponse:
    """Generate images on the network and bill per image returned."""
    spec = _model_or_404(body.model, Modality.image)

    worst_case = image_cost(spec, images=body.n)
    try:
        await assert_can_afford(session, developer.id, worst_case)
    except InsufficientBalanceError as exc:
        raise _payment_required(exc) from exc

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
    returned = [str(u) for u in (reply.get("images") or [])]
    if len(returned) > body.n:
        logger.warning(
            "node returned {} images for a request of {}; keeping {}",
            len(returned),
            body.n,
            body.n,
        )
    images = returned[: body.n]
    cost = await _charge(
        session,
        developer=developer,
        provider_id=provider_id,
        cost=image_cost(spec, images=len(images)),
        settings=settings,
    )
    return ImageGenerationResponse(
        model=body.model, images=images, cost_usdc=cost, provider_id=provider_id
    )


async def _charge(
    session, *, developer: Developer, provider_id: uuid.UUID, cost: Decimal, settings
) -> Decimal:
    """Bill a completed request.

    The work is already done here, so a shortfall cannot un-run it. The pre-dispatch gate
    is what prevents that; this raising means the balance moved underneath us, and the
    honest answer is 402 rather than silently serving free compute.
    """
    try:
        return await charge_usage(
            session,
            developer_id=developer.id,
            provider_id=provider_id,
            cost=cost,
            settings=settings,
        )
    except InsufficientBalanceError as exc:
        logger.error("could not bill developer {} for completed work: {}", developer.id, exc)
        raise _payment_required(exc) from exc


def _estimate_prompt_tokens(body: ChatCompletionRequest) -> int:
    """A cheap prompt-token estimate for the pre-dispatch gate.

    Four characters per token is the usual rough ratio. The bill normally follows the
    node's reported count, but this estimate sizes the worst case that caps it, so an
    estimate far below the truth can clamp an honest node's bill on the input side.
    The output ceiling leaves enough headroom that this stays theoretical, and it errs
    toward the developer either way. A real tokeniser here is the honest fix if it ever
    stops being theoretical.
    """
    chars = sum(len(m.content) for m in body.messages)
    return max(1, chars // 4)


def _usage_from(reply: dict, *, prompt_tokens: int, max_output_tokens: int) -> ChatUsage:
    """Token usage as the node reported it — bounded by what it was allowed to do.

    A node that omits its counts gets billed on the estimate rather than for free.

    The counts are a claim, not a measurement: only the node saw the generation, and the
    node is paid from the number it reports. `max_output_tokens` is the ceiling we sent it
    and priced the balance gate on, so a larger count is either a broken node or a lying
    one. Either way the developer does not fund it.
    """
    raw = reply.get("usage") or {}
    claimed = int(raw.get("completion_tokens") or 0)
    if claimed > max_output_tokens:
        logger.warning(
            "node claimed {} completion tokens against a ceiling of {}; billing the ceiling",
            claimed,
            max_output_tokens,
        )
    return ChatUsage(
        prompt_tokens=int(raw.get("prompt_tokens") or prompt_tokens),
        completion_tokens=min(claimed, max_output_tokens),
    )
