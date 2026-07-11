"""Session 11.4 — continuous health: throttling/errors mark a provider degraded."""

from app.config import get_settings
from app.health import evaluate_degraded
from conftest import auth, make_provider
from httpx import AsyncClient


def test_evaluate_degraded_thresholds() -> None:
    s = get_settings()
    assert evaluate_degraded({"throttling": True}, s)[0] is True
    assert evaluate_degraded({"gpu_temp_c": 95}, s)[0] is True  # over 90
    assert evaluate_degraded({"error_rate": 0.5}, s)[0] is True  # over 0.1
    assert evaluate_degraded({"gpu_temp_c": 60, "error_rate": 0.01}, s)[0] is False


async def test_throttling_provider_is_detected(client: AsyncClient) -> None:
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    # Healthy first.
    ok = await client.post(
        "/agent/health",
        headers=auth(prov_key),
        json={"gpu_temp_c": 65, "throttling": False, "error_rate": 0.0},
    )
    assert ok.json()["degraded"] is False
    me = await client.get("/providers/me", headers=auth(prov_key))
    assert me.json()["degraded"] is False

    # GPU starts throttling in production → detected.
    bad = await client.post(
        "/agent/health",
        headers=auth(prov_key),
        json={"gpu_temp_c": 92, "throttling": True, "error_rate": 0.0},
    )
    assert bad.json()["degraded"] is True and "throttl" in bad.json()["reason"]
    me2 = await client.get("/providers/me", headers=auth(prov_key))
    assert me2.json()["degraded"] is True

    # Recovery telemetry clears it.
    rec = await client.post(
        "/agent/health",
        headers=auth(prov_key),
        json={"gpu_temp_c": 60, "throttling": False, "error_rate": 0.0},
    )
    assert rec.json()["degraded"] is False
