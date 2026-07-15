"""Server-Sent Events: live job-status updates for a developer.

The client opens one long-lived connection and receives an event whenever one of
its jobs changes status. This replaces client-side polling with a server push.

Design note: the stream diffs the developer's jobs from the database on a short
interval rather than subscribing to an in-process event bus. The database is the
single source of truth and is written by *both* the API and the scheduler
process, so a DB diff sees every transition regardless of which process made it,
with no coupling to the state machine. This trades a small server-side poll for
correctness and safety; a Redis pub/sub fan-out is the scale-up path once there
are enough concurrent connections to justify it.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.db import get_sessionmaker
from app.deps import SettingsDep, require_developer
from app.models import Job
from app.schemas import JobResponse

router = APIRouter(tags=["events"])

# How often the stream re-checks the developer's jobs for changes.
POLL_INTERVAL_SECONDS = 1.5
# Emit a keep-alive comment roughly every this many seconds so proxies and the
# client can tell the connection is still alive between real events.
HEARTBEAT_SECONDS = 15.0


async def _fetch_jobs(developer_id) -> list[Job]:
    """The developer's most-recent jobs (bounded), each with its current status."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.scalars(
            select(Job)
            .where(Job.developer_id == developer_id)
            .order_by(Job.updated_at.desc())
            .limit(200)
        )
        return list(result)


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def job_event_stream(
    developer_id,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Yield SSE frames for a developer's job-status changes until disconnect.

    Extracted from the route so it can be tested directly (an infinite streaming
    response can't be consumed incrementally through the in-process ASGI test
    transport). ``is_disconnected`` lets the caller stop the loop.
    """
    # Baseline: current statuses, without replaying them to the client.
    seen = {str(j.id): j.status.value for j in await _fetch_jobs(developer_id)}
    since_beat = 0.0

    while True:
        if await is_disconnected():
            return
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        since_beat += POLL_INTERVAL_SECONDS

        jobs = await _fetch_jobs(developer_id)
        current: dict[str, str] = {}
        for job in jobs:
            jid = str(job.id)
            current[jid] = job.status.value
            if seen.get(jid) != job.status.value:
                payload = JobResponse.model_validate(job).model_dump(mode="json")
                yield _sse("job", json.dumps(payload))
        seen = current

        if since_beat >= HEARTBEAT_SECONDS:
            since_beat = 0.0
            yield ": keepalive\n\n"


@router.get("/events")
async def job_events(
    request: Request,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Stream job-status changes for the authenticated developer as SSE.

    The client establishes its baseline with a normal `GET /jobs` and then
    connects here for deltas; on reconnect it refetches to close any gap.
    """
    # Authenticate up front using a short-lived session, then release it — a
    # streaming response must not hold a DB connection for its whole lifetime.
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        developer = await require_developer(session, settings, authorization)
        developer_id = developer.id

    return StreamingResponse(
        job_event_stream(developer_id, request.is_disconnected),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )
