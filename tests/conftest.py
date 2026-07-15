"""Shared pytest fixtures. Configures a hermetic SQLite database and an ASGI client.

Unit tests touch no live Postgres/Redis: the app is pointed at an on-disk SQLite file
and the Redis health probe is stubbed per-test where needed.
"""

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

# Configure the environment BEFORE any app module reads settings (they are lru_cached).
_TMP_DB = Path(tempfile.gettempdir()) / "gridix_test.sqlite3"
os.environ["GRIDIX_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["GRIDIX_REDIS_URL"] = "redis://localhost:6379/15"
# Rate limiting now fails CLOSED (security wave 2): with no Redis in the hermetic
# suite it falls back to a local counter, so a high limit keeps the general suite
# from throttling itself. The dedicated rate-limit tests set their own low limits.
os.environ["GRIDIX_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["GRIDIX_SECRET_KEY"] = "test-secret-key-deterministic"
os.environ["GRIDIX_ENV"] = "dev"
os.environ["GRIDIX_STORAGE_LOCAL_PATH"] = str(Path(tempfile.gettempdir()) / "gridix_blobs")
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


async def register(client: AsyncClient, role: str, name: str) -> tuple[str, str]:
    """Register a developer/provider; return ``(id, api_key)``."""
    resp = await client.post(f"/{role}s", json={"name": name})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["id"], body["api_key"]


def auth(api_key: str) -> dict[str, str]:
    """Build the Authorization header for an API key."""
    return {"Authorization": f"Bearer {api_key}"}


# Well-formed 64-hex sha256 stand-ins for result refs/hashes in tests. Real proofs must be
# a valid sha256 (security wave 0 / C1), so tests use these instead of short placeholders;
# the rejection of malformed hashes is proven in test_pentest_wave0.py.
HASH_A = "a" * 64
HASH_B = "b" * 64
