"""Anti-spoofing checks for provider hardware (Session 11.6).

Catches the common tricks:

* **Faked GPU** — handled by benchmark validation (11.2): a card that can't benchmark to
  its claim is rejected.
* **One physical GPU advertised as many nodes** — the same hardware fingerprint (e.g. GPU
  UUID) appearing under multiple providers is a collision.
* **Virtualization inflating capacity** — declared VRAM far above what the benchmark
  measured means the numbers are made up.

Detections either reject the report or flag the provider for review.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BenchmarkReport, Provider

# Declared VRAM more than this ratio above measured VRAM is treated as inflation.
_VRAM_INFLATION_RATIO = 1.25


async def find_hardware_collisions(
    session: AsyncSession, fingerprint: str, provider_id: uuid.UUID
) -> list[uuid.UUID]:
    """Return other providers already advertising the same hardware fingerprint."""
    if not fingerprint:
        return []
    rows = await session.scalars(
        select(BenchmarkReport.provider_id)
        .where(
            BenchmarkReport.hardware_fingerprint == fingerprint,
            BenchmarkReport.provider_id != provider_id,
        )
        .distinct()
    )
    return list(rows)


def detect_capacity_inflation(metrics: dict, provider: Provider) -> bool:
    """Whether declared capacity materially exceeds the benchmark-measured capacity."""
    measured_vram = metrics.get("gpu_vram_mb")
    return (
        isinstance(measured_vram, int | float)
        and provider.gpu_vram_mb > 0
        and provider.gpu_vram_mb > measured_vram * _VRAM_INFLATION_RATIO
    )
