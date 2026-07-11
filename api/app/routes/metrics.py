"""Prometheus metrics — job counts by status, provider count, queue depth.

A fresh registry is built per scrape and populated from the current DB/queue state, so
values are always live and there is no cross-request metric accumulation to manage.
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from sqlalchemy import func, select

from app.deps import SessionDep
from app.models import Job, Provider
from app.redis_client import queue_depth

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics(session: SessionDep) -> Response:
    """Expose current metrics in Prometheus text format."""
    registry = CollectorRegistry()
    jobs_gauge = Gauge("gridix_jobs", "Jobs by status", ["status"], registry=registry)
    providers_gauge = Gauge("gridix_providers_total", "Registered providers", registry=registry)
    queue_gauge = Gauge("gridix_queue_depth", "Jobs waiting on the queue", registry=registry)

    rows = await session.execute(select(Job.status, func.count()).group_by(Job.status))
    for job_status, count in rows:
        jobs_gauge.labels(status=str(job_status)).set(count)

    providers_gauge.set(await session.scalar(select(func.count()).select_from(Provider)) or 0)
    try:
        queue_gauge.set(await queue_depth())
    except Exception:  # noqa: BLE001 - metrics must never fail the scrape
        queue_gauge.set(0)

    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
