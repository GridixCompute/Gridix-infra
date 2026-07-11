"""Session 7.4 — path negotiation: direct-vs-relay feasibility, fallback, recording."""

import asyncio

import pytest
from app.models import PathType
from app.paths import (
    NatType,
    ProviderChannel,
    direct_feasible,
    negotiate_path,
    provider_directly_reachable,
)
from conftest import auth, make_provider
from httpx import AsyncClient


# ── NAT feasibility matrix ──────────────────────────────────────────────────────
def test_direct_feasible_matrix() -> None:
    opn, res, sym = NatType.open, NatType.restricted, NatType.symmetric
    assert direct_feasible(opn, sym) is True  # open peer always reachable
    assert direct_feasible(sym, opn) is True
    assert direct_feasible(res, res) is True  # restricted cones can punch
    assert direct_feasible(sym, sym) is False  # two symmetric NATs cannot
    assert direct_feasible(sym, res) is False  # symmetric vs restricted: not reliable
    assert direct_feasible(res, sym) is False


def test_provider_directly_reachable() -> None:
    # A public coordinator relays only symmetric-NAT providers.
    assert provider_directly_reachable(NatType.open) is True
    assert provider_directly_reachable(NatType.restricted) is True
    assert provider_directly_reachable(NatType.symmetric) is False


# ── negotiation with fallback ───────────────────────────────────────────────────
async def test_negotiate_direct_when_check_succeeds() -> None:
    async def ok() -> bool:
        return True

    path = await negotiate_path(NatType.open, NatType.restricted, ok, timeout=1)
    assert path is PathType.direct


async def test_negotiate_relay_when_check_fails() -> None:
    async def bad() -> bool:
        return False

    assert await negotiate_path(NatType.restricted, NatType.restricted, bad, timeout=1) is (
        PathType.relay
    )


async def test_negotiate_relay_on_check_error_or_timeout() -> None:
    async def boom() -> bool:
        raise RuntimeError("udp blocked")

    async def hang() -> bool:
        await asyncio.sleep(10)
        return True

    assert await negotiate_path(NatType.open, NatType.open, boom, timeout=1) is PathType.relay
    assert await negotiate_path(NatType.open, NatType.open, hang, timeout=0.05) is PathType.relay


async def test_negotiate_skips_check_when_infeasible() -> None:
    called = False

    async def check() -> bool:
        nonlocal called
        called = True
        return True

    # Two symmetric NATs are infeasible — the (potentially expensive) check is skipped.
    path = await negotiate_path(NatType.symmetric, NatType.symmetric, check, timeout=1)
    assert path is PathType.relay
    assert called is False


# ── ProviderChannel transparent fallback ────────────────────────────────────────
async def test_channel_uses_direct_when_healthy() -> None:
    async def direct(_req: dict) -> dict:
        return {"via": "direct"}

    async def relay(_req: dict) -> dict:
        return {"via": "relay"}

    ch = ProviderChannel(PathType.direct, direct, relay)
    assert (await ch.send({}))["via"] == "direct"
    assert ch.path_type is PathType.direct


async def test_channel_falls_back_to_relay_on_direct_failure() -> None:
    async def direct(_req: dict) -> dict:
        raise ConnectionError("direct path dead")

    async def relay(_req: dict) -> dict:
        return {"via": "relay"}

    ch = ProviderChannel(PathType.direct, direct, relay)
    result = await ch.send({})
    assert result["via"] == "relay"
    # The dead direct path is downgraded so later sends skip it.
    assert ch.path_type is PathType.relay


# ── HTTP negotiation endpoint ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("nat", "expected"),
    [("open", "direct"), ("restricted", "direct"), ("symmetric", "relay")],
)
async def test_report_path_records_decision(client: AsyncClient, nat: str, expected: str) -> None:
    _pid, prov_key = await make_provider(client, "farm", cpu_cores=8, memory_mb=16000)
    resp = await client.post(
        "/agent/path",
        headers=auth(prov_key),
        json={"nat_type": nat, "candidates": [{"address": "1.2.3.4", "port": 5000}]},
    )
    assert resp.status_code == 200
    assert resp.json()["path_type"] == expected

    me = await client.get("/providers/me", headers=auth(prov_key))
    assert me.json()["path_type"] == expected
