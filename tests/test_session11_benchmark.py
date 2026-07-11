"""Session 11.1-11.2 — signed benchmark submission and validation vs declared hardware."""

from unittest.mock import AsyncMock, patch

import pytest
from app.benchmark import (
    performance_tier,
    sign_report,
    validate_benchmark,
    verify_signature,
)
from conftest import auth, make_provider
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


# ── signature ───────────────────────────────────────────────────────────────────
def test_signature_binds_report_to_key() -> None:
    metrics = {"gpu_model": "A100", "gpu_tflops": 19.0}
    sig = sign_report(metrics, "prov-key")
    assert verify_signature(metrics, sig, "prov-key")
    assert not verify_signature(metrics, sig, "other-key")
    assert not verify_signature({**metrics, "gpu_tflops": 1.0}, sig, "prov-key")


# ── validation ──────────────────────────────────────────────────────────────────
def test_validate_catches_gpu_underperformance() -> None:
    ok, _ = validate_benchmark({"gpu_tflops": 19.0}, "A100")
    assert ok
    bad, reason = validate_benchmark({"gpu_tflops": 3.0}, "A100")  # far below A100
    assert not bad and "A100" in reason
    absent, _ = validate_benchmark({}, "A100")  # claims GPU, none benchmarked
    assert not absent
    # No GPU claim → nothing to contradict.
    assert validate_benchmark({}, None)[0]


def test_performance_tier_from_throughput() -> None:
    assert performance_tier({"gpu_tflops": 67}) == "high"
    assert performance_tier({"gpu_tflops": 19}) == "mid"
    assert performance_tier({"gpu_tflops": 2}) == "low"
    assert performance_tier({}) == "cpu"


# ── endpoint: onboarding produces a signed, stored report ───────────────────────
async def test_registration_benchmark_is_stored_and_signed(client: AsyncClient) -> None:
    pid, prov_key = await make_provider(
        client, "farm", cpu_cores=8, memory_mb=16000, gpu_model="A100"
    )
    metrics = {
        "gpu_model": "A100",
        "gpu_vram_mb": 40000,
        "gpu_tflops": 19.0,
        "mem_bandwidth_gbps": 1500,
        "disk_iops": 50000,
        "network_mbps": 1000,
    }
    sig = sign_report(metrics, prov_key)

    resp = await client.post(
        "/agent/benchmark", headers=auth(prov_key), json={"metrics": metrics, "signature": sig}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["validated"] is True
    assert body["signature"] == sig  # signed by the provider key

    got = await client.get("/providers/me/benchmark", headers=auth(prov_key))
    assert got.json()["metrics"]["gpu_tflops"] == 19.0


async def test_spoofed_gpu_benchmark_is_rejected(client: AsyncClient) -> None:
    _pid, prov_key = await make_provider(
        client, "liar", cpu_cores=8, memory_mb=16000, gpu_model="A100"
    )
    metrics = {"gpu_model": "A100", "gpu_tflops": 2.0}  # claims A100, benchmarks like a T4-
    resp = await client.post(
        "/agent/benchmark",
        headers=auth(prov_key),
        json={"metrics": metrics, "signature": sign_report(metrics, prov_key)},
    )
    assert resp.status_code == 201 and resp.json()["validated"] is False
    # The lying provider is down-tiered (disabled).
    me = await client.get("/providers/me", headers=auth(prov_key))
    assert me.json()["enabled"] is False
