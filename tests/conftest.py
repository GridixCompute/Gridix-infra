"""Shared pytest fixtures. Configures a hermetic SQLite database and an ASGI client.

Unit tests touch no live Postgres/Redis: the app is pointed at an on-disk SQLite file
and the Redis health probe is stubbed per-test where needed.
"""

import atexit
import os
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

# Configure the environment BEFORE any app module reads settings (they are lru_cached).
#
# A private directory per run, NOT a fixed name in /tmp. The schema fixture drops and
# recreates every table for each test, so two suites sharing one file tear each other's
# schema down mid-test: "no such table: jobs" out of nowhere, tests that pass alone and
# fail together, and SQLite lock stalls. Nothing about that failure points at its cause,
# and it cost a wrong diagnosis before the shared file was spotted. Two runs on one
# machine — two agents, a local run beside CI — now simply cannot collide.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="gridix-test-"))
atexit.register(shutil.rmtree, _TMP_DIR, True)
_TMP_DB = _TMP_DIR / "gridix_test.sqlite3"
os.environ["GRIDIX_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["GRIDIX_REDIS_URL"] = "redis://localhost:6379/15"
# Rate limiting now fails CLOSED (security wave 2): with no Redis in the hermetic
# suite it falls back to a local counter, so a high limit keeps the general suite
# from throttling itself. The dedicated rate-limit tests set their own low limits.
os.environ["GRIDIX_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["GRIDIX_SECRET_KEY"] = "test-secret-key-deterministic"
os.environ["GRIDIX_ENV"] = "dev"
os.environ["GRIDIX_STORAGE_LOCAL_PATH"] = str(_TMP_DIR / "blobs")
# Keep long-poll holds tiny so the suite stays fast (Session 7.1).
os.environ["GRIDIX_POLL_HOLD_SECONDS"] = "0.4"
os.environ["GRIDIX_POLL_TICK_SECONDS"] = "0.05"
os.environ["GRIDIX_CONNECTION_TIMEOUT_SECONDS"] = "30"
# A valid Fernet key for the coordinator KEK (Session 9.3 key brokering).
os.environ["GRIDIX_KEK"] = "Z77HII5wps5_n_jx74p0-x0XYXk8PzX04xtf987_4Ik="
os.environ["GRIDIX_ATTESTATION_SECRET"] = "test-attestation-root-of-trust"

from app.config import get_settings  # noqa: E402
from app.db import Base, get_engine, get_sessionmaker  # noqa: E402
from app.main import create_app  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest.fixture(autouse=True)
async def _schema() -> AsyncIterator[None]:
    """Create the full schema fresh for each test and tear it down after."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An httpx client bound to the ASGI app (no network)."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def session():
    """A raw AsyncSession for tests that drive the DB directly (scheduler/reaper)."""
    async with get_sessionmaker()() as s:
        yield s


@pytest.fixture
def settings():
    """The app settings singleton (pointed at the hermetic test DB)."""
    return get_settings()


async def make_provider(client: AsyncClient, name: str, **caps) -> tuple[str, str]:
    """Register a provider and declare capabilities; return ``(id, api_key)``."""
    pid, key = await register(client, "provider", name)
    if caps:
        resp = await client.patch("/providers/me", headers=auth(key), json=caps)
        assert resp.status_code == 200, resp.text
    return pid, key


async def wallet_sign_in(client: AsyncClient, account=None) -> tuple[str, str]:
    """Real SIWE sign-in with a fresh wallet unless given one: ``(developer_id, session_key)``."""
    account = account or Account.create()
    challenge = (await client.get("/auth/nonce", params={"address": account.address})).json()
    res = await client.post(
        "/auth/verify",
        json={
            "address": account.address,
            "signature": account.sign_message(
                encode_defunct(text=challenge["message"])
            ).signature.hex(),
            "nonce": challenge["nonce"],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    return body["developer_id"], body["api_key"]


async def register(client: AsyncClient, role: str, name: str) -> tuple[str, str]:
    """Register a developer/provider through the real wallet flow; return ``(id, api_key)``.

    Neither principal has an unauthenticated factory anymore — both come to exist only via
    SIWE sign-in with a fresh wallet:

    - **developer**: sign in (which find-or-creates the account), then mint a long-lived
      *programmatic* key via ``POST /developers/me/keys``. That is the exact credential the
      deleted ``POST /developers`` returned (``ApiKeyKind.programmatic``, no expiry) — a CI
      runner's key, valid on every developer route and correctly *unable* to mint keys.
      The ``name`` argument is now cosmetic (the account is named from its address); it is
      kept so call sites read unchanged.
    - **provider**: sign in, then ``POST /providers/onboard``, which binds the provider to
      the address and mints the node's agent key.
    """
    if role == "provider":
        _, session_key = await wallet_sign_in(client)
        resp = await client.post(
            "/providers/onboard", headers=auth(session_key), json={"name": name}
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        return body["id"], body["api_key"]
    if role == "developer":
        dev_id, session_key = await wallet_sign_in(client)
        resp = await client.post(
            "/developers/me/keys", headers=auth(session_key), json={"label": name}
        )
        assert resp.status_code == 201, resp.text
        return dev_id, resp.json()["api_key"]
    raise ValueError(f"unknown role: {role!r}")


def wallet_address() -> str:
    """A unique, well-formed 0x address for tests that construct Provider rows directly.

    ``providers.wallet_address`` is NOT NULL and unique (migration 0025), so every
    directly-built Provider needs its own address even when the test never touches it.
    """
    return "0x" + uuid.uuid4().hex + uuid.uuid4().hex[:8]


def auth(api_key: str) -> dict[str, str]:
    """Build the Authorization header for an API key."""
    return {"Authorization": f"Bearer {api_key}"}


# The operator secret in the hermetic env: operator_secret is unset and env=dev, so
# operator_key falls back to GRIDIX_SECRET_KEY above. Operator-gated endpoints (dispute
# rulings, /metrics) accept this bearer.
OPERATOR_SECRET = "test-secret-key-deterministic"


def operator_auth() -> dict[str, str]:
    """Build the Authorization header for the operator secret."""
    return {"Authorization": f"Bearer {OPERATOR_SECRET}"}


# Well-formed 64-hex sha256 stand-ins for result refs/hashes in tests. Real proofs must be
# a valid sha256 (security wave 0 / C1), so tests use these instead of short placeholders;
# the rejection of malformed hashes is proven in test_pentest_wave0.py.
HASH_A = "a" * 64
HASH_B = "b" * 64
