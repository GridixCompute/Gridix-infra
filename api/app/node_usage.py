"""Reading a node's token report — the numbers it is paid from.

Shared by the unary and streamed chat paths so both clamp identically. They used to be one
function inside ``routes.inference``; streaming needs the same parsing, and importing it
back from the route would have made the route and the stream body import each other.

Every value here arrives from a counterparty with an interest in the answer, so nothing
about it may be assumed. Two rules hold throughout:

  * Nothing raises. ``int("abc")``, ``int(None)`` and ``int([1, 2])`` all throw, and an
    exception this deep becomes a 500 — a node could return one string and break every
    request routed to it, for free.
  * Nothing exceeds the ceiling the balance gate priced. A count above it is a broken node
    or a lying one, and the developer funds neither.
"""

from loguru import logger

from app.schemas import ChatUsage


def reported_tokens(raw: dict, field: str, *, default: int) -> int:
    """One token count out of a node's reply, or ``default`` if it gave nothing usable.

    Negative values are floored at zero rather than rejected: ``ChatUsage`` requires ge=0,
    so passing one through would raise ValidationError and 500 for the same reason.
    """
    value = raw.get(field)
    if value is None:
        return default
    # bool is an int subclass; True would silently mean 1 token.
    if isinstance(value, bool) or not isinstance(value, int | float):
        logger.warning(
            "node reported {}={!r}, which is not a number; using {}", field, value, default
        )
        return default
    return max(0, int(value))


def usage_from(raw_payload: dict, *, prompt_tokens: int, max_output_tokens: int) -> ChatUsage:
    """Token usage as the node reported it — bounded by what it was allowed to do.

    A node that omits its counts gets billed on the estimate rather than for free.
    """
    raw = raw_payload.get("usage")
    if not isinstance(raw, dict):
        # `usage: "x"` used to reach .get() and raise AttributeError.
        raw = {}
    claimed = reported_tokens(raw, "completion_tokens", default=0)
    if claimed > max_output_tokens:
        logger.warning(
            "node claimed {} completion tokens against a ceiling of {}; billing the ceiling",
            claimed,
            max_output_tokens,
        )
    return ChatUsage(
        prompt_tokens=reported_tokens(raw, "prompt_tokens", default=prompt_tokens),
        completion_tokens=min(claimed, max_output_tokens),
    )
