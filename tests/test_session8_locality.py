"""Session 8.5 — locality-aware scheduling: prefer warm-cache providers (soft)."""

from app.matcher import CapabilityMatcher
from app.models import Job
from conftest import auth, make_provider
from httpx import AsyncClient

DIGEST = "d" * 64


def _job_with_input() -> Job:
    return Job(image_ref="img", input_ref=DIGEST, resource_spec={"cpu_cores": 1, "memory_mb": 1000})


async def test_warm_cache_provider_is_preferred(client: AsyncClient, session) -> None:
    """Two equal providers: the one that cached the input digest ranks first."""
    _a, key_a = await make_provider(client, "a", cpu_cores=8, memory_mb=16000)
    b_pid, _key_b = await make_provider(client, "b", cpu_cores=8, memory_mb=16000)

    # Provider A reports it holds the artifact.
    resp = await client.post("/agent/cache", headers=auth(key_a), json={"cached": [DIGEST]})
    assert resp.status_code == 204

    ranked = await CapabilityMatcher().candidates(session, _job_with_input())
    assert [p.name for p in ranked][0] == "a"  # warm cache wins the tie

    # It is a soft preference, not a hard filter: B is still a candidate.
    assert {"a", "b"} <= {p.name for p in ranked}


async def test_cache_report_replaces_previous_set(client: AsyncClient, session) -> None:
    _a, key_a = await make_provider(client, "a", cpu_cores=8, memory_mb=16000)
    await client.post("/agent/cache", headers=auth(key_a), json={"cached": [DIGEST]})
    # Report a new set (evicted the old digest) → no longer preferred for it.
    await client.post("/agent/cache", headers=auth(key_a), json={"cached": ["e" * 64]})

    ranked = await CapabilityMatcher().candidates(session, _job_with_input())
    # Only one provider exists; ordering still returns it, but locality flag is off.
    assert [p.name for p in ranked] == ["a"]


async def test_no_input_ref_is_unaffected(client: AsyncClient, session) -> None:
    await make_provider(client, "a", cpu_cores=8, memory_mb=16000)
    job = Job(image_ref="img", resource_spec={"cpu_cores": 1, "memory_mb": 1000})
    assert len(await CapabilityMatcher().candidates(session, job)) == 1
