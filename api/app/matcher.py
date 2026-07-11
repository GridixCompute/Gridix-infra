"""Provider matching — pluggable policy for choosing who runs a job.

Two policies share one interface:

* :class:`CapabilityMatcher` (Session 3) — filter by declared capabilities, drop anyone
  at their concurrency limit, prefer least-loaded (reputation as tie-break).
* :class:`ReputationMatcher` (Session 5) — everything above, plus a hard stake gate
  (a provider below the minimum stake can't be assigned work) and reputation-weighted
  ordering, with a higher reputation floor for high-value jobs.

Both expose ``candidates()`` (ordered, eligible providers) so the scheduler can take one
(normal jobs) or K (redundant high-value jobs). The active policy is swappable via
``set_matcher`` — the scheduler installs :class:`ReputationMatcher` at startup.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import Select, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.ledger import provider_stake
from app.models import Job, JobStatus, Provider

# Job states that occupy a provider's concurrency slot.
_ACTIVE_STATES = (JobStatus.assigned, JobStatus.running)


class Matcher(Protocol):
    """Chooses providers for a job."""

    async def candidates(self, session: AsyncSession, job: Job) -> list[Provider]:
        """Return eligible providers, best first (may be empty)."""
        ...

    async def select(self, session: AsyncSession, job: Job) -> Provider | None:
        """Return the single best provider, or None."""
        ...


def _capability_query(job: Job) -> tuple[Select, object]:
    """Build the base query plus its load expression for capability-satisfying providers."""
    spec = job.resource_spec or {}
    need_cpu = int(spec.get("cpu_cores", 1))
    need_mem = int(spec.get("memory_mb", 0))
    need_gpu = bool(spec.get("gpu", False))
    need_vram = int(spec.get("gpu_vram_mb", 0))

    load_sq = (
        select(Job.assigned_provider_id.label("pid"), func.count().label("load"))
        .where(Job.status.in_(_ACTIVE_STATES))
        .group_by(Job.assigned_provider_id)
        .subquery()
    )
    load = func.coalesce(load_sq.c.load, literal(0))

    # Presence gate (Session 7.6): a provider that was seen and then went silent is
    # unreachable and gets no new work until it reconnects. Providers never tracked
    # (last_seen IS NULL) are not gated, so presence is opt-in per deployment.
    cutoff = datetime.now(UTC) - timedelta(seconds=get_settings().connection_timeout_seconds)

    query = (
        select(Provider, load.label("load"))
        .outerjoin(load_sq, Provider.id == load_sq.c.pid)
        .where(
            Provider.enabled.is_(True),
            Provider.cpu_cores >= need_cpu,
            Provider.memory_mb >= need_mem,
            load < Provider.max_concurrent,
            or_(Provider.last_seen.is_(None), Provider.last_seen >= cutoff),
        )
    )
    if need_gpu:
        query = query.where(Provider.gpu_model.is_not(None), Provider.gpu_vram_mb >= need_vram)
    return query, load


class CapabilityMatcher:
    """Capability filter + least-loaded selection (reputation as tie-break)."""

    async def candidates(self, session: AsyncSession, job: Job) -> list[Provider]:
        query, load = _capability_query(job)
        query = query.order_by(load.asc(), Provider.reputation.desc())
        rows = await session.execute(query)
        return [row[0] for row in rows]

    async def select(self, session: AsyncSession, job: Job) -> Provider | None:
        found = await self.candidates(session, job)
        return found[0] if found else None


class ReputationMatcher:
    """Capability + stake gate + reputation-weighted ordering.

    High-value jobs additionally require a reputation at or above
    ``high_value_min_reputation`` — the most trustworthy providers get the riskiest work.
    """

    async def candidates(self, session: AsyncSession, job: Job) -> list[Provider]:
        settings = get_settings()
        query, load = _capability_query(job)
        if job.is_high_value:
            query = query.where(Provider.reputation >= settings.high_value_min_reputation)
        # Prefer high reputation, then spare capacity.
        query = query.order_by(Provider.reputation.desc(), load.asc())
        rows = await session.execute(query)

        min_stake = Decimal(settings.min_provider_stake)
        eligible: list[Provider] = []
        for row in rows:
            provider = row[0]
            if await provider_stake(session, provider.id) >= min_stake:
                eligible.append(provider)
        return eligible

    async def select(self, session: AsyncSession, job: Job) -> Provider | None:
        found = await self.candidates(session, job)
        return found[0] if found else None


_matcher: Matcher = CapabilityMatcher()


def get_matcher() -> Matcher:
    """Return the active matching policy."""
    return _matcher


def set_matcher(matcher: Matcher) -> None:
    """Install a matching policy (the scheduler installs ReputationMatcher at startup)."""
    global _matcher
    _matcher = matcher
