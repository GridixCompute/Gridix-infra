"""Session 2 — job submission, provider capabilities, and the state machine."""

from unittest.mock import AsyncMock, patch

import pytest
from app.models import Job, JobStatus
from app.state_machine import IllegalTransitionError, can_transition, transition
from conftest import auth, register
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _no_redis():
    """Job submission enqueues to Redis; stub it for hermetic unit tests."""
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()) as m:
        yield m


async def test_submit_job_lands_queued_and_enqueues(client: AsyncClient, _no_redis) -> None:
    """A submitted job exists in ``queued`` and its id is pushed onto the queue."""
    _id, key = await register(client, "developer", "Acme")
    resp = await client.post(
        "/jobs",
        headers=auth(key),
        json={"image_ref": "ghcr.io/acme/infer:1", "resource_spec": {"cpu_cores": 2}},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == JobStatus.queued
    assert body["image_ref"] == "ghcr.io/acme/infer:1"
    _no_redis.assert_awaited_once_with(body["id"])


async def test_submit_job_requires_developer_auth(client: AsyncClient) -> None:
    """A provider key cannot submit jobs."""
    _id, prov_key = await register(client, "provider", "Farm")
    resp = await client.post("/jobs", headers=auth(prov_key), json={"image_ref": "img"})
    assert resp.status_code == 403


async def test_gpu_job_without_vram_is_rejected(client: AsyncClient) -> None:
    """gpu=true with no vram is rejected before it is ever queued."""
    _id, key = await register(client, "developer", "Acme")
    resp = await client.post(
        "/jobs",
        headers=auth(key),
        json={"image_ref": "img", "resource_spec": {"gpu": True, "gpu_vram_mb": 0}},
    )
    assert resp.status_code == 422


async def test_unknown_input_ref_is_rejected(client: AsyncClient) -> None:
    """Referencing a blob that was never uploaded is a 400."""
    _id, key = await register(client, "developer", "Acme")
    resp = await client.post(
        "/jobs",
        headers=auth(key),
        json={"image_ref": "img", "input_ref": "deadbeef"},
    )
    assert resp.status_code == 400


async def test_blob_upload_then_submit_with_ref(client: AsyncClient) -> None:
    """Upload input, then submit a job referencing it end to end."""
    _id, key = await register(client, "developer", "Acme")
    files = {"file": ("in.bin", b"payload", "application/octet-stream")}
    up = await client.post("/blobs", headers=auth(key), files=files)
    assert up.status_code == 201, up.text
    ref = up.json()["ref"]

    resp = await client.post(
        "/jobs", headers=auth(key), json={"image_ref": "img", "input_ref": ref}
    )
    assert resp.status_code == 201
    assert resp.json()["input_ref"] == ref


async def test_developer_sees_only_own_jobs(client: AsyncClient) -> None:
    """Listing and reading are scoped to the calling developer."""
    _a, key_a = await register(client, "developer", "A")
    _b, key_b = await register(client, "developer", "B")
    r = await client.post("/jobs", headers=auth(key_a), json={"image_ref": "img"})
    job_id = r.json()["id"]

    # Owner sees it; the other developer gets 404, not a leak.
    assert (await client.get(f"/jobs/{job_id}", headers=auth(key_a))).status_code == 200
    assert (await client.get(f"/jobs/{job_id}", headers=auth(key_b))).status_code == 404

    listed = await client.get("/jobs", headers=auth(key_b))
    assert listed.json() == []


async def test_provider_declares_and_reads_capabilities(client: AsyncClient) -> None:
    """PATCH updates only supplied fields; GET reads them back."""
    _id, key = await register(client, "provider", "Farm")
    patch_resp = await client.patch(
        "/providers/me",
        headers=auth(key),
        json={"gpu_model": "A100", "gpu_vram_mb": 40000, "cpu_cores": 32, "max_concurrent": 4},
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    assert body["gpu_model"] == "A100"
    assert body["max_concurrent"] == 4

    me = await client.get("/providers/me", headers=auth(key))
    assert me.json()["gpu_vram_mb"] == 40000


# ── State machine unit tests ────────────────────────────────────────────────────
def test_legal_and_illegal_transitions() -> None:
    """The transition table permits the lifecycle and forbids shortcuts."""
    assert can_transition(JobStatus.queued, JobStatus.assigned)
    assert can_transition(JobStatus.assigned, JobStatus.running)
    assert can_transition(JobStatus.running, JobStatus.completed)
    assert can_transition(JobStatus.running, JobStatus.queued)  # reassign
    # Illegal: cannot jump queued → completed, or leave a terminal state.
    assert not can_transition(JobStatus.queued, JobStatus.completed)
    assert not can_transition(JobStatus.completed, JobStatus.running)


def test_transition_stamps_timestamps_and_rejects_illegal() -> None:
    """transition() sets lifecycle timestamps and raises on an illegal move."""
    job = Job(image_ref="img", status=JobStatus.queued, resource_spec={})
    transition(job, JobStatus.assigned)
    assert job.status is JobStatus.assigned and job.assigned_at is not None
    transition(job, JobStatus.running)
    assert job.started_at is not None
    transition(job, JobStatus.completed)
    assert job.finished_at is not None and job.lease_expires_at is None

    with pytest.raises(IllegalTransitionError):
        transition(job, JobStatus.running)  # completed is terminal
