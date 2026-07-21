"""The public free tier: what it serves, and what bounds it.

The free path deliberately does NOT reuse ``/v1``. That path is the product: it gates on a
balance, reserves a hold before dispatch, and settles against the ledger afterwards. None of
that has a meaning here, because there is no payer — a hold of zero against nobody is not a
weaker version of the gate, it is the gate removed. Opening ``/v1`` to anonymous callers
would mean the paid product's own dispatch path served people who never pay, with the
balance check as the only thing that had been holding it shut.

So the free tier reuses only the two pieces that carry no billing semantics — node selection
and the relay — and is bounded by RATE instead of by money:

  * a model allowlist, so the paid catalogue is unreachable from here,
  * a per-IP request rate, so "unlimited chat" cannot mean "one script owns the GPU",
  * a concurrency cap with a bounded queue, so load waits its turn instead of thrashing,
  * a daily counter for image generation, anchored per WALLET.

Chat and images are bounded differently because they carry different risk. Chat is anonymous
and unmetered by design, so an IP rate is the only ceiling available. Image generation
requires a wallet session, so its limit can be counted against a real identity — which is
also what makes prompt screening meaningful, since a refused request now belongs to someone
rather than to an address behind a NAT.

THE FREE MODEL IS NOT IN ``CATALOG``. The catalogue is what GRIDIX sells, with prices, and
is what ``/v1/models`` advertises and what the billing gate prices against. Adding a
zero-priced entry there would make the free model dispatchable through the paid path and
advertise it as a product. Node selection reads ``provider_models`` (what nodes declare),
not the catalogue, so a free model can be servable without being sellable.
"""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FreeTierUsage

# The one chat model the public tier serves. Small on purpose: a 3B model is ~2GB of VRAM,
# so one A4500 can hold several copies in parallel and serve many visitors at once, where a
# single 8B generation would monopolise the card.
FREE_CHAT_MODEL = "llama3.2-3b"


def is_free_chat_model(model: str | None) -> bool:
    """True only for the exact free chat model. An allowlist, never a pattern.

    A prefix or substring test here would be the whole vulnerability: `llama` matching
    `llama-3.1-70b` would let an anonymous caller run the expensive paid model for free.
    """
    return model == FREE_CHAT_MODEL


def utc_day(now: datetime | None = None) -> str:
    """The current UTC calendar day, as the quota's reset boundary defines it.

    Explicitly UTC and explicitly a string: the limit resets at 00:00 UTC, so the day has to
    be computed in UTC regardless of where the server or the database thinks it lives.
    """
    return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%d")


def wallet_anchor(address: str) -> str:
    """The identity an image quota is counted against: one wallet, one allowance.

    This replaces the cookie+IP pair the quota used while image generation was anonymous.
    That scheme existed to make a limit mean something without an identity, and it was a
    deterrent at best — a cookie wipe reset it, and a shared NAT address made the IP half
    unfair to everyone behind it. Requiring a wallet session removes the problem rather than
    mitigating it: the caller HAS an identity, so the quota is counted against that and
    nothing else. Both anchors are gone rather than kept "just in case", because a second
    way to count the same limit is a second way for it to disagree with itself.

    Lowercased first: EIP-55 checksummed and all-lowercase spellings of an address are the
    same account, and counting them separately would hand out ten images a day to anyone who
    noticed.

    Still hashed, so the counter table stays a counter rather than a record of which wallet
    generated what and when. The address is public on-chain; the association between it and
    this activity does not have to be.
    """
    return _hash("wallet", address.strip().lower())


def _hash(kind: str, value: str) -> str:
    return hashlib.sha256(f"gridix-free-tier:{kind}:{value}".encode()).hexdigest()[:64]


async def consume_daily(
    session: AsyncSession,
    *,
    anchor: str,
    kind: str,
    limit: int,
    now: datetime | None = None,
) -> bool:
    """Charge one unit of ``anchor``'s daily allowance. True if it was within the limit.

    Reads and writes under the row lock so two concurrent requests cannot both see four and
    both become five — the same reasoning as the balance gate, for the same reason: a
    limit that is only checked optimistically is not a limit under concurrency.

    Nothing is deleted on a new day; the day is part of the key, so yesterday's row simply
    stops being consulted. That keeps the reset free of a scheduled job, which is one fewer
    thing that can fail silently at midnight.
    """
    day = utc_day(now)
    row = await session.scalar(
        select(FreeTierUsage)
        .where(
            FreeTierUsage.anchor == anchor,
            FreeTierUsage.kind == kind,
            FreeTierUsage.day == day,
        )
        .with_for_update()
    )
    if row is None:
        row = FreeTierUsage(anchor=anchor, kind=kind, day=day, count=0)
        session.add(row)
        await session.flush()

    if row.count >= limit:
        return False
    row.count += 1
    await session.commit()
    return True


async def used_today(
    session: AsyncSession, *, anchor: str, kind: str, now: datetime | None = None
) -> int:
    """How much of the daily allowance ``anchor`` has spent. Reads nothing into existence."""
    row = await session.scalar(
        select(FreeTierUsage).where(
            FreeTierUsage.anchor == anchor,
            FreeTierUsage.kind == kind,
            FreeTierUsage.day == utc_day(now),
        )
    )
    return row.count if row else 0
