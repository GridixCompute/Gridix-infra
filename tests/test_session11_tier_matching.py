"""Session 11.5 — matching uses measured health: degraded providers are down-tiered."""

from app.matcher import CapabilityMatcher
from app.models import Job
from conftest import auth, make_provider
from httpx import AsyncClient


def _job() -> Job:
    return Job(image_ref="img", resource_spec={"cpu_cores": 1, "memory_mb": 1000})


async def test_degraded_provider_is_excluded(client: AsyncClient, session) -> None:
    _healthy, hkey = await make_provider(client, "healthy", cpu_cores=8, memory_mb=16000)
    _bad, bkey = await make_provider(client, "throttled", cpu_cores=8, memory_mb=16000)

    # 'throttled' reports throttling → degraded.
    await client.post("/agent/health", headers=auth(bkey), json={"throttling": True})
    await client.post("/agent/health", headers=auth(hkey), json={"throttling": False})

    names = [p.name for p in await CapabilityMatcher().candidates(session, _job())]
    assert "healthy" in names
    assert "throttled" not in names  # measured degradation excludes it


async def test_recovered_provider_is_eligible_again(client: AsyncClient, session) -> None:
    _p, key = await make_provider(client, "p", cpu_cores=8, memory_mb=16000)
    await client.post("/agent/health", headers=auth(key), json={"throttling": True})
    assert not await CapabilityMatcher().candidates(session, _job())
    await client.post("/agent/health", headers=auth(key), json={"throttling": False})
    assert len(await CapabilityMatcher().candidates(session, _job())) == 1
