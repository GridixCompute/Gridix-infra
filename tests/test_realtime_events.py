"""The SSE stream pushes a job's status changes to its developer only.

The streaming generator is driven directly: an infinite SSE response can't be
consumed incrementally through the in-process ASGI test transport (it buffers),
so we exercise `job_event_stream` and reserve the HTTP client for the auth path.
"""

import asyncio
import json
import uuid

from app.db import get_sessionmaker
from app.models import Job, JobStatus
from app.routes.events import job_event_stream
from app.state_machine import transition
from conftest import auth, register
from httpx import AsyncClient


async def _submit_job(client: AsyncClient, key: str) -> str:
    resp = await client.post(
        "/jobs",
        headers=auth(key),
        json={
            "image_ref": "ghcr.io/acme/x:latest",
            "resource_spec": {"cpu_cores": 1, "memory_mb": 512, "gpu": False, "gpu_vram_mb": 0},
            "timeout_seconds": 300,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _set_status(job_id: str, target: JobStatus) -> None:
    async with get_sessionmaker()() as s:
        job = await s.get(Job, uuid.UUID(job_id))
        assert job is not None
        transition(job, target)
        await s.commit()


async def _collect(developer_id, stop_flag: dict, out: list[str]) -> None:
    async def is_disconnected() -> bool:
        return stop_flag["stop"]

    async for frame in job_event_stream(developer_id, is_disconnected):
        out.append(frame)


def _job_events(frames: list[str]) -> list[dict]:
    """Parse the `data:` payloads out of collected SSE frames."""
    events = []
    for frame in frames:
        for line in frame.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events


async def test_events_pushes_status_change(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setattr("app.routes.events.POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr("app.routes.events.HEARTBEAT_SECONDS", 1000.0)

    dev_id, key = await register(client, "developer", "rt-dev")
    job_id = await _submit_job(client, key)

    stop = {"stop": False}
    frames: list[str] = []
    task = asyncio.create_task(_collect(uuid.UUID(dev_id), stop, frames))

    await asyncio.sleep(0.2)  # let the stream take its baseline (queued)
    await _set_status(job_id, JobStatus.assigned)
    await asyncio.sleep(0.3)  # let the next poll emit the delta
    stop["stop"] = True
    await asyncio.wait_for(task, timeout=5.0)

    events = _job_events(frames)
    assert any(e["id"] == job_id and e["status"] == "assigned" for e in events), events


async def test_events_only_streams_own_jobs(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setattr("app.routes.events.POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr("app.routes.events.HEARTBEAT_SECONDS", 1000.0)

    alice_id, _ = await register(client, "developer", "alice")
    _, bob_key = await register(client, "developer", "bob")
    bob_job = await _submit_job(client, bob_key)

    stop = {"stop": False}
    frames: list[str] = []
    task = asyncio.create_task(_collect(uuid.UUID(alice_id), stop, frames))

    await asyncio.sleep(0.2)
    await _set_status(bob_job, JobStatus.assigned)  # Bob's job, not Alice's
    await asyncio.sleep(0.3)
    stop["stop"] = True
    await asyncio.wait_for(task, timeout=5.0)

    assert _job_events(frames) == [], "Alice must not see Bob's job events"


async def test_events_requires_developer_auth(client: AsyncClient) -> None:
    # No credentials -> 401.
    resp = await client.get("/events")
    assert resp.status_code == 401

    # A provider key -> 403 (this is a developer-only stream).
    _, pkey = await register(client, "provider", "rt-prov")
    resp = await client.get("/events", headers=auth(pkey))
    assert resp.status_code == 403
