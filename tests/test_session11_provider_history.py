"""Session 11.6 — a provider reads back its own job history and reputation events."""

import uuid
from datetime import UTC, datetime, timedelta

from app.models import (
    AttemptOutcome,
    Job,
    JobAttempt,
    JobKind,
    JobStatus,
    ReputationEvent,
    ReputationKind,
)
from conftest import auth, make_provider, register
from httpx import AsyncClient


async def _seed_job(session, developer_id: uuid.UUID, status: JobStatus) -> Job:
    job = Job(
        developer_id=developer_id,
        kind=JobKind.standard,
        status=status,
        image_ref="ghcr.io/acme/trainer:latest",
        is_high_value=True,
        redundancy=3,
    )
    session.add(job)
    await session.flush()
    return job


async def test_job_history_reports_this_providers_attempts(client: AsyncClient, session) -> None:
    dev_id, _ = await register(client, "developer", "dev")
    pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    other_id, other_key = await make_provider(client, "rival", cpu_cores=4, memory_mb=8000)

    job = await _seed_job(session, uuid.UUID(dev_id), JobStatus.completed)
    started = datetime.now(UTC)
    session.add(
        JobAttempt(
            job_id=job.id,
            provider_id=uuid.UUID(pid),
            attempt_number=1,
            outcome=AttemptOutcome.completed,
            started_at=started,
            finished_at=started + timedelta(seconds=42),
        )
    )
    # A second job the OTHER provider ran — must not leak into our history.
    other_job = await _seed_job(session, uuid.UUID(dev_id), JobStatus.failed)
    session.add(
        JobAttempt(
            job_id=other_job.id,
            provider_id=uuid.UUID(other_id),
            attempt_number=1,
            outcome=AttemptOutcome.failed,
        )
    )
    await session.commit()

    rows = (await client.get("/providers/me/jobs", headers=auth(prov_key))).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["job_id"] == str(job.id)
    assert row["outcome"] == "completed"
    assert row["job_status"] == "completed"
    assert row["image_ref"] == "ghcr.io/acme/trainer:latest"
    assert row["is_high_value"] is True
    assert row["redundancy"] == 3
    assert row["duration_seconds"] == 42.0

    # The rival sees only its own failed attempt.
    rival_rows = (await client.get("/providers/me/jobs", headers=auth(other_key))).json()
    assert len(rival_rows) == 1
    assert rival_rows[0]["outcome"] == "failed"
    assert rival_rows[0]["duration_seconds"] is None


async def test_reputation_history_is_scoped_and_ordered(client: AsyncClient, session) -> None:
    pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    puid = uuid.UUID(pid)

    session.add(
        ReputationEvent(
            provider_id=puid,
            kind=ReputationKind.job_success,
            delta=2.0,
            score_after=52.0,
        )
    )
    session.add(
        ReputationEvent(
            provider_id=puid,
            kind=ReputationKind.slash,
            delta=-10.0,
            score_after=42.0,
            meta={"reason": "canary_fail"},
        )
    )
    await session.commit()

    rows = (await client.get("/providers/me/reputation", headers=auth(prov_key))).json()
    assert len(rows) == 2
    # Newest first — the slash was added last.
    assert rows[0]["kind"] == "slash"
    assert rows[0]["delta"] == -10.0
    assert rows[0]["meta"] == {"reason": "canary_fail"}
    assert rows[1]["kind"] == "job_success"


async def test_history_requires_provider_credentials(client: AsyncClient) -> None:
    _dev_id, dev_key = await register(client, "developer", "dev")
    assert (await client.get("/providers/me/jobs", headers=auth(dev_key))).status_code == 403
    assert (await client.get("/providers/me/reputation", headers=auth(dev_key))).status_code == 403
