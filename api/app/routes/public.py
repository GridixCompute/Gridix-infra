"""The public playground: chat without an account, bounded by rate rather than by money.

These endpoints are unauthenticated by design, which makes what they DON'T do the important
part. They reuse exactly two things from the paid path — node selection and the relay — and
skip everything that carries billing meaning:

  * no ``reserve_balance``: there is no payer, so there is nothing to hold,
  * no ``settle_reservation`` / ``release_reservation``: nothing is charged, ever,
  * no ledger postings at all: a free request leaves the books untouched,
  * no catalogue lookup: the free model is not sellable and is not priced.

Reusing ``/v1`` instead would have meant opening the paid product's own dispatch path to
anonymous callers with the balance check — the only thing holding it shut — removed. The
separation is not tidiness; it is the reason a free tier cannot become a way to get the paid
product for nothing.

What bounds it instead:
  * a MODEL ALLOWLIST — one exact id, so the paid catalogue is unreachable from here,
  * a PER-IP RATE — "unlimited" means no quota, not no ceiling,
  * a CONCURRENCY CAP with a bounded queue — load waits, then is honestly refused,
  * a DAILY COUNT for images, which is moot while that route is closed.
"""

from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from app.deps import SessionDep, SettingsDep, WalletSessionDep
from app.dispatch import (
    DispatchError,
    NoNodeAvailableError,
    dispatch,
    dispatch_stream,
    select_node,
)
from app.free_capacity import CapacityFull, get_capacity
from app.free_tier import (
    FREE_CHAT_MODEL,
    FREE_IMAGE_MODEL,
    consume_daily,
    is_free_chat_model,
    used_today,
    wallet_anchor,
)
from app.image_artifacts import store_node_images
from app.models import DataTier
from app.moderation import get_moderator, image_generation_available
from app.ratelimit import check_rate_limit
from app.schemas import ChatMessage
from app.siwe import utcnow
from app.storage import get_storage
from app.streaming_chat import sse

router = APIRouter(prefix="/public", tags=["public"])


class PublicChatRequest(BaseModel):
    """A free chat turn.

    ``model`` is accepted but not trusted: whatever arrives, the served model is the free
    one. Taking the caller's value would make the allowlist a suggestion.
    """

    messages: list[ChatMessage] = Field(min_length=1, max_length=32)
    model: str | None = None
    max_tokens: int = Field(default=512, ge=1, le=2048)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


def _client_ip(request: Request) -> str:
    """The caller's address, for rate limiting only.

    Reads the socket peer, NOT ``X-Forwarded-For``: that header is caller-supplied, so
    trusting it lets anyone reset their own rate limit by inventing an address. A deployment
    behind a proxy has to be configured to rewrite the peer (uvicorn ``--proxy-headers`` with
    a trusted-host list), which is a deployment decision rather than something this code may
    assume.
    """
    client = request.client
    return client.host if client else "unknown"


@router.get("/models")
async def public_models() -> dict:
    """What the free tier serves. Deliberately not the paid catalogue."""
    return {
        "chat": [{"id": FREE_CHAT_MODEL, "free": True}],
        "images": [],
        "images_available": image_generation_available(),
    }


@router.post("/chat")
async def public_chat(
    body: PublicChatRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> StreamingResponse:
    """Stream a free chat completion. No account, no balance, no ledger entry.

    Streamed rather than unary because it is what makes the queue tolerable: a caller who
    waited for a slot starts seeing tokens the moment they get one.
    """
    ip = _client_ip(request)

    # The ceiling that makes "unlimited" safe. Checked before a node is chosen so a flood
    # costs a Redis increment rather than a dispatch.
    if not await check_rate_limit(f"free-chat:ip:{ip}", settings.free_chat_rate_per_minute):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Wait a moment and try again.",
            headers={"Retry-After": "60"},
        )

    # The allowlist. `model` is ignored rather than validated-and-rejected: there is exactly
    # one thing this endpoint serves, and silently serving it is friendlier than a 400 for a
    # field the caller had no reason to think mattered.
    if body.model is not None and not is_free_chat_model(body.model):
        logger.info("public chat ignored requested model {!r}", body.model)

    try:
        provider_id = await select_node(
            session,
            model=FREE_CHAT_MODEL,
            now=utcnow(),
            settings=settings,
            data_tier=DataTier.public,
        )
    except NoNodeAvailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The free model is offline right now. Try again shortly.",
        ) from exc

    payload = {
        "model": FREE_CHAT_MODEL,
        "messages": [m.model_dump(mode="json") for m in body.messages],
        "max_tokens": body.max_tokens,
        "temperature": body.temperature,
        "stream": True,
    }

    capacity = get_capacity(
        slots=settings.free_chat_concurrency, queue_depth=settings.free_chat_queue_depth
    )

    async def body_stream() -> AsyncIterator[str]:
        try:
            async with capacity.slot():
                async for frame in dispatch_stream(
                    provider_id, method="chat.completions", payload=payload, settings=settings
                ):
                    kind = frame.get("type")
                    if kind == "chunk":
                        delta = frame.get("delta")
                        if isinstance(delta, str) and delta:
                            yield sse(_chunk(delta))
                        continue
                    if kind == "error" or int(frame.get("status", 200) or 200) >= 400:
                        yield sse({"error": {"message": "The model failed to answer."}})
                        break
                    if kind == "response":
                        break
                # No usage frame and no cost: there is nothing to bill, and emitting a
                # zero cost would imply an account this caller does not have.
                yield sse(_done())
                yield sse("[DONE]")
        except CapacityFull:
            yield sse({"error": {"message": "Busy right now. Try again in a moment."}})
            yield sse("[DONE]")
        except DispatchError as exc:
            logger.warning("public chat dispatch failed: {}", exc)
            yield sse({"error": {"message": "The model failed to answer."}})
            yield sse("[DONE]")

    return StreamingResponse(
        body_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _chunk(delta: str) -> dict:
    """An OpenAI-shaped chunk, so the same client parser reads free and paid streams."""
    return {
        "object": "chat.completion.chunk",
        "model": FREE_CHAT_MODEL,
        "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
    }


def _done() -> dict:
    return {
        "object": "chat.completion.chunk",
        "model": FREE_CHAT_MODEL,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }


@router.get("/images/quota")
async def image_quota(
    developer: WalletSessionDep, session: SessionDep, settings: SettingsDep
) -> dict:
    """How much of today's image allowance this WALLET has left.

    Gated on the same wallet session as generation itself: the allowance belongs to an
    address, so there is no answer to give a caller who has not proved they hold one. It
    also means the number the UI shows is the number that will actually be enforced, rather
    than a guess made against a different anchor.
    """
    if developer.wallet_address is None:
        # Unreachable via wallet sign-in, which always sets it. Explicit because a quota
        # counted against "no address" would be one shared allowance for everybody.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A wallet address is required.",
        )
    used = await used_today(session, anchor=wallet_anchor(developer.wallet_address), kind="image")
    return {
        "limit": settings.free_images_per_day,
        "used": used,
        "remaining": max(0, settings.free_images_per_day - used),
        "resets": "00:00 UTC",
        "available": image_generation_available(),
    }


class PublicImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)


@router.post("/images")
async def public_image(
    body: PublicImageRequest,
    developer: WalletSessionDep,
    session: SessionDep,
    settings: SettingsDep,
) -> dict:
    """Generate an image. Requires a WALLET SESSION — unlike chat, which stays anonymous.

    The asymmetry is the point. Chat is cheap to serve and cheap to get wrong, so it is
    open. Image generation is neither: it is the surface where a prompt filter has to hold,
    and a filter is worth far more when the request belongs to an identity than when it
    comes from an address behind a NAT. Requiring a session is what makes the quota
    countable, the refusals attributable, and repeat abuse something that can be acted on.

    Order of checks, each refusing before the next costs anything:
      1. a wallet session at all (the dependency),
      2. prompt screening — before a node, before the quota is spent,
      3. the daily allowance for this wallet.

    Screening runs BEFORE the quota so a refused prompt does not consume an allowance. A
    caller whose prompt is rejected has not had an image, and charging them for one would
    turn the filter into a way to burn someone else's day.
    """
    if developer.wallet_address is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A wallet address is required.",
        )

    moderator = get_moderator()
    if not moderator.is_configured():
        # Fail-closed at the gate: no screening, no generation.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image generation is unavailable.",
        )

    verdict = await moderator.check_prompt(body.prompt)
    if not verdict.allowed:
        logger.warning(
            "refused image prompt from developer {} ({})", developer.id, verdict.category
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That prompt was refused. GRIDIX won't generate sexual material involving "
                "minors, or sexual content depicting real people."
            ),
        )

    if not await consume_daily(
        session,
        anchor=wallet_anchor(developer.wallet_address),
        kind="image",
        limit=settings.free_images_per_day,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"You've used today's {settings.free_images_per_day} free images. "
                "Resets at 00:00 UTC."
            ),
        )

    # Dispatch to a node serving the free image model, exactly as the paid path does — same
    # model, same node, same by-value reply. The difference is only what surrounds it: no
    # balance, no ledger, the wallet quota above instead. The node returns the image inline
    # as base64; the coordinator stores it and returns a reachable URL (never the node's own,
    # which a browser cannot reach and which dies with the node).
    try:
        provider_id = await select_node(
            session,
            model=FREE_IMAGE_MODEL,
            now=utcnow(),
            settings=settings,
            data_tier=DataTier.public,
        )
    except NoNodeAvailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No node can generate images right now. Try again shortly.",
        ) from exc

    try:
        reply = await dispatch(
            provider_id,
            method="images.generations",
            payload={"model": FREE_IMAGE_MODEL, "prompt": body.prompt, "n": 1},
            settings=settings,
        )
    except DispatchError as exc:
        logger.warning("public image dispatch to {} failed: {}", provider_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The image model failed to answer.",
        ) from exc

    urls = await store_node_images(reply.get("images"), settings=settings)
    if not urls:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The image model returned no image.",
        )
    return {
        "created": int(utcnow().timestamp()),
        "data": [{"url": urls[0]}],
        "model": FREE_IMAGE_MODEL,
    }


@router.get("/image/{ref}")
async def public_image_file(ref: str) -> Response:
    """Serve a generated image by its content-addressed ref — the URL /public/images hands back.

    Unauthenticated on purpose: a browser ``<img>`` loads it with no credentials, and the ref
    is a sha256 nobody can guess, so there is nothing to gate. ``get_storage().get`` verifies
    the bytes hash to the ref before returning them (storage integrity, Session 8.2).
    """
    try:
        data = await get_storage().get(ref)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such image.") from exc
    return Response(content=data, media_type="image/png")
