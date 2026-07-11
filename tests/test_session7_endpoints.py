"""Session 7.5 — endpoint-style jobs: token, port publishing, and the routed gateway."""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from app.models import Job, JobStatus
from app.security import endpoint_token, verify_endpoint_token
from conftest import auth, make_provider, register
from httpx import AsyncClient

from agent import build_run_argv

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


# ── endpoint capability token ───────────────────────────────────────────────────
def test_endpoint_token_is_deterministic_and_verifiable() -> None:
    jid = str(uuid.uuid4())
    tok = endpoint_token(jid, "secret")
    assert endpoint_token(jid, "secret") == tok  # deterministic
    assert verify_endpoint_token(jid, tok, "secret")
    assert not verify_endpoint_token(jid, tok, "other-secret")
    assert not verify_endpoint_token(str(uuid.uuid4()), tok, "secret")


# ── hardened port publishing ────────────────────────────────────────────────────
def test_build_run_argv_publishes_endpoint_port() -> None:
    argv = build_run_argv(
        image_ref="srv",
        container_name="c",
        input_path=None,
        output_dir=Path("/tmp/o"),
        resource_spec={"cpu_cores": 1, "memory_mb": 512},
        allow_egress=False,
        enable_gpu=False,
        exposed_port=8080,
    )
    joined = " ".join(argv)
    assert "-p 127.0.0.1:8080:8080" in joined  # loopback-only publish
    assert "--network bridge" in joined  # endpoint must be reachable
    # Still hardened.
    assert "--cap-drop ALL" in joined and "--read-only" in joined


# ── endpoint info ───────────────────────────────────────────────────────────────
async def test_get_endpoint_returns_url_and_token(client: AsyncClient, settings) -> None:
    _dev, dev_key = await register(client, "developer", "acme")
    r = await client.post(
        "/jobs", headers=auth(dev_key), json={"image_ref": "srv", "exposed_port": 8080}
    )
    job_id = r.json()["id"]
    info = await client.get(f"/jobs/{job_id}/endpoint", headers=auth(dev_key))
    assert info.status_code == 200
    body = info.json()
    assert body["port"] == 8080
    assert body["url"].endswith(f"/endpoints/{job_id}/")
    assert body["token"] == endpoint_token(job_id, settings.secret_key)


async def test_get_endpoint_409_when_no_port(client: AsyncClient) -> None:
    _dev, dev_key = await register(client, "developer", "acme")
    r = await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "batch"})
    resp = await client.get(f"/jobs/{r.json()['id']}/endpoint", headers=auth(dev_key))
    assert resp.status_code == 409


# ── routed gateway ──────────────────────────────────────────────────────────────
async def _live_endpoint_job(client: AsyncClient, session) -> tuple[uuid.UUID, str]:
    """Submit an endpoint job and force it live (running, assigned to a provider)."""
    pid, _ = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "acme")
    r = await client.post(
        "/jobs", headers=auth(dev_key), json={"image_ref": "srv", "exposed_port": 8080}
    )
    job_id = uuid.UUID(r.json()["id"])
    job = await session.get(Job, job_id)
    job.status = JobStatus.running
    job.assigned_provider_id = uuid.UUID(pid)
    await session.commit()
    return job_id, dev_key


async def test_gateway_forwards_to_provider(client: AsyncClient, session, settings) -> None:
    """A token-authed call is bridged to the provider and its reply is returned."""
    job_id, _dev_key = await _live_endpoint_job(client, session)
    token = endpoint_token(str(job_id), settings.secret_key)

    reply = {"status": 201, "payload": {"body": "pong", "content_type": "text/plain"}}
    with patch("app.routes.endpoints.call_provider", new=AsyncMock(return_value=reply)) as call:
        resp = await client.post(
            f"/endpoints/{job_id}/predict",
            headers={"X-Endpoint-Token": token},
            content=b'{"q":1}',
        )
    assert resp.status_code == 201
    assert resp.text == "pong"
    # The forwarded payload targets the right port/path/method.
    payload = call.await_args.kwargs["payload"]
    assert payload["port"] == 8080
    assert payload["path"] == "/predict"
    assert payload["method"] == "POST"


async def test_gateway_rejects_bad_token(client: AsyncClient, session) -> None:
    job_id, _dev_key = await _live_endpoint_job(client, session)
    resp = await client.get(f"/endpoints/{job_id}/x", headers={"X-Endpoint-Token": "wrong"})
    assert resp.status_code == 401


async def test_gateway_409_when_not_live(client: AsyncClient, settings) -> None:
    _dev, dev_key = await register(client, "developer", "acme")
    r = await client.post(
        "/jobs", headers=auth(dev_key), json={"image_ref": "srv", "exposed_port": 8080}
    )
    job_id = r.json()["id"]  # still queued, not running
    token = endpoint_token(job_id, settings.secret_key)
    resp = await client.get(f"/endpoints/{job_id}/x", headers={"X-Endpoint-Token": token})
    assert resp.status_code == 409
