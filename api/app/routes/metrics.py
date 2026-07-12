"""Prometheus metrics for the control plane.

A fresh registry is built per scrape and populated from current DB / queue / storage state,
so values are always live and there is no cross-request accumulation to manage. Everything is
wrapped so a dependency being down (Redis, storage) reports as a 0/down gauge rather than
failing the scrape — the point of metrics is to stay observable *during* an outage.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from sqlalchemy import func, select

from app.deps import SessionDep, SettingsDep
from app.ledger import verify_ledger_integrity
from app.models import Job, JobStatus, LedgerDirection, LedgerEntry, Provider
from app.redis_client import queue_depth
from app.storage import get_storage

router = APIRouter(tags=["metrics"])

# A content-addressed ref that will never exist; exists() probes the backend cheaply.
_HEALTH_SENTINEL = "0" * 64


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile (portable; avoids Postgres-only percentile_cont)."""
    if not values:
        return 0.0
    xs = sorted(values)
    k = (len(xs) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@router.get("/metrics")
async def metrics(session: SessionDep, settings: SettingsDep) -> Response:
    """Expose current metrics in Prometheus text format."""
    reg = CollectorRegistry()
    g_jobs = Gauge("gridix_jobs", "Jobs by status", ["status"], registry=reg)
    g_prov = Gauge("gridix_providers_total", "Registered providers", registry=reg)
    g_prov_conn = Gauge(
        "gridix_providers_connected", "Providers seen within the connection timeout", registry=reg
    )
    g_queue = Gauge("gridix_queue_depth", "Jobs waiting on the queue", registry=reg)
    g_debit = Gauge("gridix_ledger_debit_total", "Sum of ledger debits", registry=reg)
    g_credit = Gauge("gridix_ledger_credit_total", "Sum of ledger credits", registry=reg)
    g_disc = Gauge(
        "gridix_ledger_discrepancies", "Unbalanced ledger groups (must be 0)", registry=reg
    )
    g_dur = Gauge(
        "gridix_job_duration_seconds", "Completed job duration", ["quantile"], registry=reg
    )
    g_redis = Gauge("gridix_redis_up", "1 if Redis is reachable", registry=reg)
    g_storage = Gauge("gridix_storage_up", "1 if blob storage is reachable", registry=reg)

    # Jobs by status.
    for job_status, count in await session.execute(
        select(Job.status, func.count()).group_by(Job.status)
    ):
        g_jobs.labels(status=str(job_status)).set(count)

    # Providers: total and currently connected (last_seen within the timeout).
    g_prov.set(await session.scalar(select(func.count()).select_from(Provider)) or 0)
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.connection_timeout_seconds)
    g_prov_conn.set(
        await session.scalar(
            select(func.count())
            .select_from(Provider)
            .where(Provider.last_seen.is_not(None), Provider.last_seen >= cutoff)
        )
        or 0
    )

    # Ledger: totals (should track equal) + per-group discrepancy count (the money invariant).
    g_debit.set(
        float(
            await session.scalar(
                select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                    LedgerEntry.direction == LedgerDirection.debit
                )
            )
            or 0
        )
    )
    g_credit.set(
        float(
            await session.scalar(
                select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                    LedgerEntry.direction == LedgerDirection.credit
                )
            )
            or 0
        )
    )
    g_disc.set(len(await verify_ledger_integrity(session)))

    # Job duration p50/p95 over recent completed jobs.
    durations = [
        (_as_utc(f) - _as_utc(s)).total_seconds()
        for s, f in await session.execute(
            select(Job.started_at, Job.finished_at)
            .where(
                Job.status == JobStatus.completed,
                Job.started_at.is_not(None),
                Job.finished_at.is_not(None),
            )
            .order_by(Job.finished_at.desc())
            .limit(1000)
        )
    ]
    g_dur.labels(quantile="0.5").set(_percentile(durations, 0.5))
    g_dur.labels(quantile="0.95").set(_percentile(durations, 0.95))

    # Dependency health — a down dependency is a 0 gauge, never a failed scrape. Bound each
    # probe so a hung/unreachable backend can't slow the scrape into a timeout (which would
    # make the series go stale and flap the alerts).
    try:
        g_queue.set(await asyncio.wait_for(queue_depth(), timeout=2.0))
        g_redis.set(1)
    except Exception:  # noqa: BLE001 - Redis down/slow: report it, don't fail the scrape
        g_queue.set(0)
        g_redis.set(0)
    try:
        await asyncio.wait_for(get_storage().exists(_HEALTH_SENTINEL), timeout=2.0)
        g_storage.set(1)
    except Exception:  # noqa: BLE001 - storage down/slow: report it, don't fail the scrape
        g_storage.set(0)

    return Response(generate_latest(reg), media_type=CONTENT_TYPE_LATEST)
