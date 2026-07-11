"""Session 11.6 — anti-spoofing: shared GPU and inflated capacity are caught."""

import pytest
from app.antispoof import detect_capacity_inflation
from app.benchmark import sign_report
from app.models import Provider
from conftest import auth, make_provider
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _no_redis():
    from unittest.mock import AsyncMock, patch

    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


async def _submit(client, key, metrics):
    return await client.post(
        "/agent/benchmark",
        headers=auth(key),
        json={"metrics": metrics, "signature": sign_report(metrics, key)},
    )


def test_capacity_inflation_unit() -> None:
    p = Provider(name="p", gpu_vram_mb=80000)
    assert detect_capacity_inflation({"gpu_vram_mb": 16000}, p) is True  # claims 80G, has 16G
    assert detect_capacity_inflation({"gpu_vram_mb": 80000}, p) is False


async def test_one_gpu_as_many_nodes_is_caught(client: AsyncClient) -> None:
    _a, akey = await make_provider(client, "node-a", cpu_cores=8, memory_mb=16000)
    _b, bkey = await make_provider(client, "node-b", cpu_cores=8, memory_mb=16000)
    metrics = {"gpu_tflops": 19.0, "hardware_fingerprint": "GPU-UUID-DEADBEEF"}

    first = await _submit(client, akey, metrics)
    assert first.json()["validated"] is True
    # Same physical GPU advertised under a second provider → collision.
    second = await _submit(client, bkey, metrics)
    assert second.json()["validated"] is False
    me = await client.get("/providers/me", headers=auth(bkey))
    assert me.json()["enabled"] is False


async def test_inflated_capacity_is_flagged(client: AsyncClient) -> None:
    _p, key = await make_provider(client, "liar", cpu_cores=8, memory_mb=16000, gpu_vram_mb=80000)
    # Declares 80G VRAM but benchmarks 16G.
    resp = await _submit(client, key, {"gpu_tflops": 19.0, "gpu_vram_mb": 16000})
    assert resp.json()["validated"] is False
    me = await client.get("/providers/me", headers=auth(key))
    assert me.json()["enabled"] is False
