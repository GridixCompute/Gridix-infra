"""Session 6 — pricing, idempotency, rate limiting, metrics, and error shape."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.config import get_settings
from app.pricing import compute_cost, escrow_estimate, protocol_fee
from app.ratelimit import check_rate_limit
from conftest import auth, register
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("_no_redis")


@pytest.fixture
def _no_redis():
    with patch("app.routes.jobs.enqueue_job", new=AsyncMock()):
        yield


# ── pricing ─────────────────────────────────────────────────────────────────────
def test_pricing_scales_with_cpu_gpu_and_duration() -> None:
    s = get_settings()
    # base_job_price=1 per cpu-core-minute. 2 cores × 2 minutes = 4.
    assert compute_cost({"cpu_cores": 2}, 120, s) == Decimal("4")
    # GPU is 4× the CPU rate.
    assert compute_cost({"cpu_cores": 1, "gpu": True}, 60, s) == Decimal("4")
    # Escrow holds the worst case (full timeout).
    assert escrow_estimate({"cpu_cores": 1}, 300, s) == Decimal("5")


def test_protocol_fee() -> None:
    s = get_settings()  # protocol_fee_bps=250 → 2.5%
    assert protocol_fee(Decimal("4"), s) == Decimal("0.1")


# ── idempotency ─────────────────────────────────────────────────────────────────
async def test_idempotent_submit_returns_same_job(client: AsyncClient) -> None:
    _dev, key = await register(client, "developer", "Acme")
    headers = {**auth(key), "Idempotency-Key": "abc-123"}
    first = await client.post("/jobs", headers=headers, json={"image_ref": "img"})
    second = await client.post("/jobs", headers=headers, json={"image_ref": "img"})
    assert first.status_code == 201
    assert first.json()["id"] == second.json()["id"]


# ── rate limiting ───────────────────────────────────────────────────────────────
class _FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, ttl: int) -> bool:
        return True


async def test_rate_limit_blocks_after_threshold() -> None:
    fake = _FakeRedis()
    with patch("app.ratelimit.get_redis", return_value=fake):
        results = [await check_rate_limit("id", limit=3) for _ in range(4)]
    assert results == [True, True, True, False]


async def test_rate_limit_fails_open_when_redis_down() -> None:
    with patch("app.ratelimit.get_redis", side_effect=RuntimeError("no redis")):
        assert await check_rate_limit("id", limit=1) is True


# ── metrics ─────────────────────────────────────────────────────────────────────
async def test_metrics_exposes_counts(client: AsyncClient) -> None:
    _dev, key = await register(client, "developer", "Acme")
    await client.post("/jobs", headers=auth(key), json={"image_ref": "img"})
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert "gridix_jobs" in body
    assert "gridix_providers_total" in body
    assert "gridix_queue_depth" in body


# ── structured errors ───────────────────────────────────────────────────────────
async def test_error_responses_are_structured(client: AsyncClient) -> None:
    _dev, key = await register(client, "developer", "Acme")
    resp = await client.get("/jobs/00000000-0000-0000-0000-000000000000", headers=auth(key))
    assert resp.status_code == 404
    assert resp.json()["error"]["type"] == "http_error"
