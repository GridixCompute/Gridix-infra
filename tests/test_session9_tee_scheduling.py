"""Session 9.4 — confidential-tee jobs schedule only to attested-TEE providers."""

import uuid

from app.matcher import CapabilityMatcher
from app.models import DataTier, Job, Provider
from conftest import make_provider
from httpx import AsyncClient


def _tee_job() -> Job:
    return Job(
        image_ref="img",
        resource_spec={"cpu_cores": 1, "memory_mb": 1000},
        data_tier=DataTier.confidential_tee,
    )


async def _set_tee(session, pid: str, value: bool) -> None:
    provider = await session.get(Provider, uuid.UUID(pid))
    provider.tee_attested = value
    await session.commit()


async def test_confidential_job_only_goes_to_tee_provider(client: AsyncClient, session) -> None:
    non_tee, _ = await make_provider(client, "plain", cpu_cores=8, memory_mb=16000)
    tee, _ = await make_provider(client, "enclave", cpu_cores=8, memory_mb=16000)
    await _set_tee(session, tee, True)

    ranked = await CapabilityMatcher().candidates(session, _tee_job())
    names = [p.name for p in ranked]
    assert names == ["enclave"]  # non-TEE provider is excluded entirely
    assert non_tee not in [str(p.id) for p in ranked]


async def test_no_tee_provider_means_no_candidate(client: AsyncClient, session) -> None:
    await make_provider(client, "plain", cpu_cores=8, memory_mb=16000)
    assert await CapabilityMatcher().candidates(session, _tee_job()) == []


async def test_public_job_unaffected_by_tee(client: AsyncClient, session) -> None:
    await make_provider(client, "plain", cpu_cores=8, memory_mb=16000)
    public = Job(image_ref="img", resource_spec={"cpu_cores": 1, "memory_mb": 1000})
    assert len(await CapabilityMatcher().candidates(session, public)) == 1
