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

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from app.deps import SessionDep, SettingsDep
from app.dispatch import DispatchError, NoNodeAvailableError, dispatch_stream, select_node
from app.free_capacity import CapacityFull, get_capacity
from app.free_tier import (
    FREE_CHAT_MODEL,
    anchor_for,
    consume_daily,
    is_free_chat_model,
    new_visitor_id,
    used_today,
)
from app.models import DataTier
from app.moderation import image_generation_available
from app.ratelimit import check_rate_limit
from app.schemas import ChatMessage
from app.siwe import utcnow
from app.streaming_chat import sse

router = APIRouter(prefix="/public", tags=["public"])

VISITOR_COOKIE = "gridix_visitor"


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
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> dict:
    """How much of today's image allowance this visitor has left.

    Readable even though generation is closed, because the counter is what the UI shows and
    the reset boundary is what a visitor asks about. Issues the visitor cookie if absent, so
    the anchor exists before the first generation rather than being minted mid-request.
    """
    cookie = request.cookies.get(VISITOR_COOKIE)
    if not cookie:
        cookie = new_visitor_id()
        response.set_cookie(
            VISITOR_COOKIE,
            cookie,
            max_age=60 * 60 * 24 * 400,
            httponly=True,
            samesite="lax",
            secure=settings.is_prod,
        )
    cookie_anchor, _ = anchor_for(_client_ip(request), cookie)
    used = await used_today(session, anchor=cookie_anchor, kind="image")
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
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> dict:
    """Generate a free image — CLOSED, and closed by the safety system rather than a flag.

    Two independent reasons this cannot serve anything today, and the check order matters:

    1. NO MODERATION IS CONFIGURED. `image_generation_available()` is false whenever the
       moderator cannot make decisions, and the default moderator cannot. Public,
       unauthenticated image generation without CSAM and NCII screening is not something to
       ship behind a TODO, so the door is shut by the absence of the control rather than by
       a boolean someone could flip without noticing what it guards.
    2. NOTHING CAN GENERATE AN IMAGE. The node package serves chat only and answers
       `images.generations` with 501; no node advertises an image model.

    The quota below it is real and tested regardless, so that enabling this route later is
    supplying a moderator — not also discovering that the limit was never written.
    """
    if not image_generation_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Free image generation isn't available yet. It stays closed until content "
                "screening is in place."
            ),
        )

    # Unreachable while the gate above holds. Kept, exercised by tests with a moderator
    # installed, and deliberately written before the route opens: a quota added at the same
    # time as the feature is a quota nobody has ever seen fail.
    cookie = request.cookies.get(VISITOR_COOKIE) or new_visitor_id()
    cookie_anchor, ip_anchor = anchor_for(_client_ip(request), cookie)

    within_visitor = await consume_daily(
        session, anchor=cookie_anchor, kind="image", limit=settings.free_images_per_day
    )
    within_ip = await consume_daily(
        session, anchor=ip_anchor, kind="image", limit=settings.free_images_per_ip_per_day
    )
    if not (within_visitor and within_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"You've used today's {settings.free_images_per_day} free images. "
                "Resets at 00:00 UTC."
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="No node can generate images yet.",
    )
