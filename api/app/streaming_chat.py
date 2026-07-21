"""Streamed chat completions: the SSE body, and the billing that has to survive it.

Streaming breaks an assumption the unary path was built on. There, the cost is known when
the reply arrives and the hold is settled in the same breath. Here the reservation is taken
before dispatch (unchanged — F1's pre-dispatch gate is not weakened by this) but the usage
only becomes known at the END of a stream that may never reach its end. The request can now
stop in three ways, and each owes the ledger something different:

  * the node finished        -> settle for the usage it reported, clamped to the ceiling
  * the CLIENT went away     -> settle for the tokens ACTUALLY generated, release the rest
  * the node or tunnel died  -> release the whole hold; nothing is charged

The middle case is the one with teeth, and it is why this module exists rather than a few
more lines in the route. A disconnected client is not a failure: the provider really did
burn GPU on the tokens it produced, and refunding those would make "stop generating" a free
way to consume a node. Equally, the developer must not pay for the tokens that were never
produced, and the hold must not be left in escrow because the task carrying it was
cancelled. So the disconnect path bills the partial and returns the remainder.

Two mechanics make that safe, and both are easy to get wrong:

  1. THE SETTLE RUNS IN A SHIELDED TASK. Cancellation is what tells us the client left, so
     the cleanup is running inside an already-cancelled task; a bare `await` there raises
     CancelledError immediately and the hold is stranded in escrow forever. The finaliser is
     therefore spawned as its own task and awaited through a shield, so the cancellation
     that triggered it cannot also abort it. Strong references are held until it completes,
     because a task nobody references can be garbage-collected mid-flight.

  2. IT USES ITS OWN DB SESSION. The request's session is closed when the handler returns,
     which for a streaming response is long before the stream ends. Settling on it would
     fail exactly when it matters most. (``events.py`` releases the request session for the
     same reason.)
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing, suppress
from decimal import Decimal

from loguru import logger

from app.catalog import ModelSpec, chat_cost
from app.config import Settings
from app.db import get_sessionmaker
from app.dispatch import DispatchError, dispatch_stream
from app.node_usage import usage_from
from app.schemas import ChatUsage
from app.usage_billing import release_reservation, settle_reservation

# Finaliser tasks in flight. A task that nothing holds a reference to may be collected
# before it runs to completion, which on this path would mean a hold silently left in
# escrow — the one outcome this module exists to prevent.
_finalisers: set[asyncio.Task] = set()


def sse(data: dict | str) -> str:
    """One SSE frame. ``[DONE]`` is a bare token, not JSON, exactly as OpenAI sends it."""
    body = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))
    return f"data: {body}\n\n"


def _chunk(completion_id: str, created: int, model: str, delta: dict, finish: str | None) -> dict:
    """One OpenAI ``chat.completion.chunk``."""
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def _reported_tokens(frame: dict) -> int | None:
    """A node's cumulative token count off a chunk frame, if it sent a usable one.

    The node is paid from this number, so nothing about it may be assumed: a string, a bool
    (which is an int subclass and would read as 1) or a negative would each be a way to
    mis-bill. Anything unusable is treated as absent, and the caller falls back to counting
    frames.
    """
    value = frame.get("tokens")
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return max(0, int(value))


class _Accounting:
    """Running state the billing decision is made from when the stream ends, however it ends."""

    def __init__(
        self, *, spec: ModelSpec, prompt_tokens: int, max_output: int, worst_case: Decimal
    ):
        self.spec = spec
        self.prompt_tokens = prompt_tokens
        self.max_output = max_output
        self.worst_case = worst_case
        # Tokens we have evidence the node actually produced. Only ever grows.
        self.emitted = 0
        # Set when the node sends its terminal frame with a usage report.
        self.final: ChatUsage | None = None

    def saw_chunk(self, frame: dict) -> None:
        """Account for one delivered chunk.

        Prefers the node's own cumulative count and falls back to counting frames, which is
        what a node that reports nothing gets billed on. Either way the result is clamped to
        the ceiling the gate priced, so a node cannot bill past it by inflating its count.
        """
        reported = _reported_tokens(frame)
        self.emitted = reported if reported is not None else self.emitted + 1
        self.emitted = min(self.emitted, self.max_output)

    def completion_tokens(self) -> int:
        """What to bill for, whether or not the stream reached its end."""
        if self.final is not None:
            return min(self.final.completion_tokens, self.max_output)
        return min(self.emitted, self.max_output)

    def prompt_billed(self) -> int:
        """Input tokens to charge for.

        The node's own count when it finished and reported one — which is what the unary
        path bills on, and the two must not disagree for the same request. Only when the
        stream ended early (no report exists) does this fall back to the coordinator's
        pre-dispatch upper bound.
        """
        return self.final.prompt_tokens if self.final is not None else self.prompt_tokens

    def billable(self) -> Decimal:
        """The charge, clamped to the reservation exactly as the unary path clamps it."""
        return min(
            chat_cost(
                self.spec,
                input_tokens=self.prompt_billed(),
                output_tokens=self.completion_tokens(),
            ),
            self.worst_case,
        )

    def partial_billable(self) -> Decimal:
        """The charge for a stream that ended before the node finished.

        Zero tokens produced means zero charge, not the prompt's cost. The node did read the
        prompt, so billing prefill would be arguable — but "a request that produced nothing
        is not charged" is the rule the unary path already holds to, and a stream that
        emitted no token has produced nothing the developer can use. Charging a fraction of
        a cent for it would also make the disconnect path disagree with the node-failure
        path, which releases in full after the same prefill work.
        """
        return self.billable() if self.completion_tokens() > 0 else Decimal(0)


async def _settle(
    *,
    developer_id: uuid.UUID,
    provider_id: uuid.UUID,
    held: Decimal,
    actual: Decimal,
    settings: Settings,
) -> Decimal:
    """Charge ``actual`` against the hold, on a session of this stream's own."""
    async with get_sessionmaker()() as session:
        return await settle_reservation(
            session,
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            actual=actual,
            settings=settings,
        )


async def _release(*, developer_id: uuid.UUID, held: Decimal) -> None:
    """Return the whole hold, charging nothing."""
    async with get_sessionmaker()() as session:
        await release_reservation(session, developer_id=developer_id, held=held)


async def _run_shielded(coro) -> None:
    """Run ``coro`` to completion even if the caller is being cancelled.

    Awaiting a shield from an already-cancelled task raises CancelledError at the await —
    but the shielded task keeps running, which is the point: the hold is resolved either
    way. Suppressing here only means we stop *waiting*, not that we stop the work.
    """
    task = asyncio.create_task(coro)
    _finalisers.add(task)
    task.add_done_callback(_finalisers.discard)
    with suppress(asyncio.CancelledError):
        await asyncio.shield(task)


async def chat_stream_body(
    *,
    spec: ModelSpec,
    model: str,
    payload: dict,
    developer_id: uuid.UUID,
    provider_id: uuid.UUID,
    held: Decimal,
    worst_case: Decimal,
    prompt_tokens: int,
    max_output: int,
    created: int,
    settings: Settings,
) -> AsyncIterator[str]:
    """Yield the SSE body for one streamed completion, settling the hold however it ends.

    Extracted from the route so the money paths can be driven directly. A streaming response
    cannot be consumed incrementally through the in-process ASGI transport, and the
    disconnect case in particular is only reachable by closing the generator by hand.
    """
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    books = _Accounting(
        spec=spec, prompt_tokens=prompt_tokens, max_output=max_output, worst_case=worst_case
    )
    settled = False
    node_failed = False

    try:
        # OpenAI opens with a role-only delta; clients rely on it to start a message.
        yield sse(_chunk(completion_id, created, model, {"role": "assistant"}, None))

        async with aclosing(
            dispatch_stream(
                provider_id, method="chat.completions", payload=payload, settings=settings
            )
        ) as frames:
            async for frame in frames:
                kind = frame.get("type")
                if kind == "chunk":
                    delta = frame.get("delta")
                    if not isinstance(delta, str) or delta == "":
                        # A malformed or empty chunk is skipped, not fatal: one bad frame
                        # from a node must not 500 a stream the developer is already
                        # reading, and it is not evidence of a token either.
                        continue
                    books.saw_chunk(frame)
                    yield sse(_chunk(completion_id, created, model, {"content": delta}, None))
                    continue

                if kind == "error":
                    node_failed = True
                    logger.warning("stream from {} failed: {}", provider_id, frame)
                    break

                if kind != "response":
                    # Only `response` ends a stream successfully. An unrecognised frame type
                    # is a protocol violation, and treating it as a terminal success would
                    # let a node truncate its own stream — ending the generation early while
                    # still being paid for what it had emitted. Ignore it and keep reading;
                    # the inter-frame timeout still bounds a node that has nothing more.
                    logger.warning("ignoring unknown stream frame type {!r}", kind)
                    continue

                if int(frame.get("status", 200) or 200) >= 400:
                    node_failed = True
                    logger.warning("stream from {} failed: {}", provider_id, frame)
                    break

                # Terminal success frame: take the node's usage report if it made one.
                node_payload = frame.get("payload")
                if isinstance(node_payload, dict):
                    books.final = usage_from(
                        node_payload,
                        prompt_tokens=prompt_tokens,
                        max_output_tokens=max_output,
                    )
                break

        if node_failed:
            await _release(developer_id=developer_id, held=held)
            settled = True
            yield sse({"error": {"message": "The node failed to complete the request."}})
            yield sse("[DONE]")
            return

        cost = await _settle(
            developer_id=developer_id,
            provider_id=provider_id,
            held=held,
            actual=books.billable(),
            settings=settings,
        )
        settled = True

        usage = ChatUsage(
            prompt_tokens=books.final.prompt_tokens if books.final else prompt_tokens,
            completion_tokens=books.completion_tokens(),
        )
        finish = "length" if usage.completion_tokens >= max_output else "stop"
        yield sse(_chunk(completion_id, created, model, {}, finish))
        # Usage and cost ride a final chunk, the way OpenAI sends usage when asked for it.
        # `cost_usdc` and `provider_id` stay Gridix extras, as on the unary response — a
        # client that streams should not have to make a second call to learn what it paid.
        yield sse(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [],
                "usage": usage.model_dump(mode="json"),
                "cost_usdc": str(cost),
                "provider_id": str(provider_id),
            }
        )
        yield sse("[DONE]")

    except DispatchError as exc:
        # The stream never started — the relay was unreachable or the node was gone. The
        # response headers are already sent by now (the role delta went out first), so
        # raising would drop the connection and leave the client to infer what happened
        # from a stream that simply stops. Every other failure path here ends with an error
        # event and `[DONE]`; this one does too, so a client has exactly one shape to
        # handle: a terminated stream that never carried a usage frame.
        logger.warning("stream to {} never started: {}", provider_id, exc)
        await _release(developer_id=developer_id, held=held)
        settled = True
        yield sse({"error": {"message": "The node failed to complete the request."}})
        yield sse("[DONE]")
    finally:
        if not settled:
            # The only ways here: the consumer stopped reading (client disconnect, the case
            # this whole module is shaped around), or something unexpected escaped. Either
            # way the provider is paid for what it really produced and the rest goes back.
            await _run_shielded(
                _finalise_partial(
                    developer_id=developer_id,
                    provider_id=provider_id,
                    held=held,
                    actual=books.partial_billable(),
                    settings=settings,
                )
            )


async def _finalise_partial(
    *,
    developer_id: uuid.UUID,
    provider_id: uuid.UUID,
    held: Decimal,
    actual: Decimal,
    settings: Settings,
) -> None:
    """Resolve a hold for a stream that ended early. Never raises.

    An exception escaping here would leave the hold in escrow — the failure mode with no
    recovery path, since nothing later knows the reservation existed. Logging and moving on
    is worse than settling correctly and better than every alternative.
    """
    try:
        if actual > 0:
            await _settle(
                developer_id=developer_id,
                provider_id=provider_id,
                held=held,
                actual=actual,
                settings=settings,
            )
        else:
            await _release(developer_id=developer_id, held=held)
    except Exception as exc:  # noqa: BLE001 - a stranded hold is worse than a logged error
        logger.error("failed to resolve hold {} for developer {}: {}", held, developer_id, exc)
