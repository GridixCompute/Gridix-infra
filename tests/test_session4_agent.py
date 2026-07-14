"""Session 4 — sandbox hardening (pure) and the result-intake endpoints (API)."""

import hashlib
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from app.assignment import assign_job
from app.models import JobStatus
from conftest import auth, make_provider, register
from httpx import AsyncClient

from agent import build_run_argv, sha256_hex


# ── Sandbox hardening (no Docker needed) ────────────────────────────────────────
def _argv(**overrides) -> list[str]:
    base = {
        "image_ref": "ghcr.io/acme/job:1",
        "container_name": "gridix-x",
        "input_path": None,
        "output_dir": Path("/tmp/out"),
        "resource_spec": {"cpu_cores": 2, "memory_mb": 2048},
        "allow_egress": False,
        "enable_gpu": False,
    }
    base.update(overrides)
    return build_run_argv(**base)


def test_container_is_hardened_by_default() -> None:
    """Every default-deny control the isolation story depends on is present."""
    argv = _argv()
    joined = " ".join(argv)
    assert "--network none" in joined  # no egress by default
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--read-only" in joined
    assert "--pids-limit 512" in joined
    assert "--user 65534:65534" in joined  # non-root
    assert "--memory 2048m" in joined
    assert "--cpus 2" in joined
    assert argv[-1] == "ghcr.io/acme/job:1"  # image is the final positional arg


def test_egress_only_when_requested() -> None:
    """Network is enabled solely when the job explicitly opts into egress."""
    assert "--network none" in " ".join(_argv(allow_egress=False))
    assert "--network bridge" in " ".join(_argv(allow_egress=True))


def test_gpu_flag_gated_by_capability() -> None:
    """--gpus is added only when the job wants a GPU and the host enables it."""
    spec = {"cpu_cores": 1, "memory_mb": 512, "gpu": True}
    assert "--gpus" not in _argv(resource_spec=spec, enable_gpu=False)
    assert "--gpus" in _argv(resource_spec=spec, enable_gpu=True)


def test_gpu_defaults_to_all_when_no_devices_pinned() -> None:
    spec = {"cpu_cores": 1, "memory_mb": 512, "gpu": True}
    argv = _argv(resource_spec=spec, enable_gpu=True)
    i = argv.index("--gpus")
    assert argv[i + 1] == "all"


def test_gpu_pins_to_configured_devices() -> None:
    """With devices configured, the job is confined to exactly those GPUs (isolation), not all."""
    spec = {"cpu_cores": 1, "memory_mb": 512, "gpu": True}
    argv = _argv(resource_spec=spec, enable_gpu=True, gpu_devices="GPU-abc,GPU-def")
    i = argv.index("--gpus")
    assert argv[i + 1] == "device=GPU-abc,GPU-def"
    assert "all" not in argv[i + 1]


def test_gpu_devices_ignored_without_capability() -> None:
    """No --gpus at all when the job doesn't want a GPU, even if devices are configured."""
    spec = {"cpu_cores": 1, "memory_mb": 512}  # gpu not requested
    assert "--gpus" not in _argv(resource_spec=spec, enable_gpu=True, gpu_devices="0")


def test_input_mounted_read_only() -> None:
    """A provided input path is bind-mounted read-only."""
    argv = _argv(input_path=Path("/tmp/in"))
    assert "/tmp/in:/gridix/input:ro" in argv


def test_sha256_hex_matches_stdlib() -> None:
    """The proof anchor is a plain sha256 over the output bytes."""
    assert sha256_hex(b"hello") == hashlib.sha256(b"hello").hexdigest()


# ── Result intake (API) ─────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


async def _assigned_running_job(client: AsyncClient, session, settings) -> tuple:
    """Set up a provider+developer, submit a job, assign it, and report running."""
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "Acme")
    r = await client.post("/jobs", headers=auth(dev_key), json={"image_ref": "img"})
    job_id = uuid.UUID(r.json()["id"])
    await assign_job(session, job_id, settings)
    await client.post(
        f"/agent/jobs/{job_id}/status", headers=auth(prov_key), json={"status": "running"}
    )
    return job_id, prov_key, dev_key


async def test_result_completes_job_and_is_downloadable(
    client: AsyncClient, session, settings
) -> None:
    """A clean result completes the job; the developer can download it."""
    job_id, prov_key, dev_key = await _assigned_running_job(client, session, settings)

    output = b"the answer is 42"
    up = await client.post(
        "/agent/blobs",
        headers=auth(prov_key),
        files={"file": ("result", output, "application/octet-stream")},
    )
    ref = up.json()["ref"]
    resp = await client.post(
        f"/agent/jobs/{job_id}/result",
        headers=auth(prov_key),
        json={
            "result_ref": ref,
            "exit_code": 0,
            "proof": {"output_sha256": sha256_hex(output), "exit_code": 0},
            "timed_out": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == JobStatus.completed

    dl = await client.get(f"/jobs/{job_id}/result", headers=auth(dev_key))
    assert dl.status_code == 200 and dl.content == output


async def test_nonzero_exit_fails_job(client: AsyncClient, session, settings) -> None:
    """A nonzero exit code lands the job in `failed`."""
    job_id, prov_key, _dev_key = await _assigned_running_job(client, session, settings)
    resp = await client.post(
        f"/agent/jobs/{job_id}/result",
        headers=auth(prov_key),
        json={"result_ref": None, "exit_code": 1, "proof": {"exit_code": 1}, "timed_out": False},
    )
    assert resp.json()["status"] == JobStatus.failed


async def test_timeout_marks_job_timeout(client: AsyncClient, session, settings) -> None:
    """A timed-out run lands the job in `timeout`."""
    job_id, prov_key, _dev_key = await _assigned_running_job(client, session, settings)
    resp = await client.post(
        f"/agent/jobs/{job_id}/result",
        headers=auth(prov_key),
        json={"result_ref": None, "exit_code": 124, "proof": {"exit_code": 124}, "timed_out": True},
    )
    assert resp.json()["status"] == JobStatus.timeout


async def test_proof_mismatch_is_rejected(client: AsyncClient, session, settings) -> None:
    """A proof whose output hash does not match the stored ref is rejected."""
    job_id, prov_key, _dev_key = await _assigned_running_job(client, session, settings)
    resp = await client.post(
        f"/agent/jobs/{job_id}/result",
        headers=auth(prov_key),
        json={
            "result_ref": "0000000000000000000000000000000000000000000000000000000000000000",
            "exit_code": 0,
            "proof": {"output_sha256": "deadbeef"},
            "timed_out": False,
        },
    )
    assert resp.status_code == 400


async def test_agent_downloads_input(client: AsyncClient, session, settings) -> None:
    """The agent can fetch a job's input blob it was assigned."""
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    _dev, dev_key = await register(client, "developer", "Acme")
    files = {"file": ("in.bin", b"input-bytes", "application/octet-stream")}
    ref = (await client.post("/blobs", headers=auth(dev_key), files=files)).json()["ref"]
    r = await client.post(
        "/jobs", headers=auth(dev_key), json={"image_ref": "img", "input_ref": ref}
    )
    job_id = uuid.UUID(r.json()["id"])
    await assign_job(session, job_id, settings)

    dl = await client.get(f"/agent/jobs/{job_id}/input", headers=auth(prov_key))
    assert dl.status_code == 200 and dl.content == b"input-bytes"
