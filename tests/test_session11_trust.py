"""Session 11.3 — attested providers flagged; unattested fall back to benchmark-only."""

from app.attestation import sign_measurement
from app.benchmark import sign_report, trust_source
from app.config import get_settings
from conftest import auth, make_provider
from httpx import AsyncClient


def test_trust_source_ranking() -> None:
    assert trust_source(tee_attested=True, has_validated_benchmark=True) == "attested"
    assert trust_source(tee_attested=False, has_validated_benchmark=True) == "benchmark"
    assert trust_source(tee_attested=False, has_validated_benchmark=False) == "self_report"


async def test_unattested_falls_back_to_benchmark(client: AsyncClient, session) -> None:
    pid, prov_key = await make_provider(
        client, "farm", cpu_cores=8, memory_mb=16000, gpu_model="A100"
    )
    # No attestation yet, no benchmark → self_report.
    t0 = (await client.get("/providers/me/trust", headers=auth(prov_key))).json()
    assert t0 == {"attested": False, "benchmarked": False, "trust_source": "self_report"}

    # Submit a valid benchmark → falls back to benchmark trust.
    metrics = {"gpu_model": "A100", "gpu_tflops": 19.0}
    await client.post(
        "/agent/benchmark",
        headers=auth(prov_key),
        json={"metrics": metrics, "signature": sign_report(metrics, prov_key)},
    )
    t1 = (await client.get("/providers/me/trust", headers=auth(prov_key))).json()
    assert t1["benchmarked"] is True and t1["trust_source"] == "benchmark"


async def test_attested_provider_is_flagged(client: AsyncClient, session) -> None:
    _pid, prov_key = await make_provider(client, "enclave", cpu_cores=8, memory_mb=16000)
    quote = {
        "measurement": "m",
        "signature": sign_measurement("m", get_settings().attestation_secret),
    }
    await client.post("/agent/attest", headers=auth(prov_key), json=quote)

    t = (await client.get("/providers/me/trust", headers=auth(prov_key))).json()
    assert t["attested"] is True and t["trust_source"] == "attested"
