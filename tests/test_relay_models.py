"""A node's tunnel publishes what it serves, so the coordinator can find it.

This file is async-only. The WebSocket side of the same story lives in
test_session7_relay.py, where the sync TestClient pattern already works: mixing a
blocking TestClient into a module of async DB tests wedges the event loop for every
file that runs after it.

So: here we prove the registry writes hit the database; there we prove the tunnel
handler calls them. Neither covers "connecting a node makes it dispatchable" alone.
"""

import uuid
from datetime import UTC, datetime

import pytest
from app.config import get_settings
from app.models import Provider, ProviderModel
from app.presence import is_connected
from app.relay import (
    _clean_models,
    clear_models,
    mark_provider_seen,
    record_models,
)
from conftest import wallet_address
from sqlalchemy import select

# ── The registry writes actually hit the database (async units) ──────────────────


@pytest.fixture
async def provider(session) -> Provider:
    p = Provider(name="gpu-farm", wallet_address=wallet_address())
    session.add(p)
    await session.commit()
    # commit() expires the instance; refresh so tests can read its columns without
    # tripping a lazy load from sync context.
    await session.refresh(p)
    return p


async def _models_of(session, provider_id: uuid.UUID) -> set[str]:
    session.expire_all()
    rows = await session.scalars(
        select(ProviderModel.model).where(ProviderModel.provider_id == provider_id)
    )
    return set(rows.all())


class TestRegistryWrites:
    async def test_record_models_persists_them(self, session, provider) -> None:
        await record_models(provider.id, ["llama-3-70b", "sdxl"])
        assert await _models_of(session, provider.id) == {"llama-3-70b", "sdxl"}

    async def test_record_models_replaces_rather_than_merges(self, session, provider) -> None:
        """The live tunnel is the current truth: a model the node no longer runs must
        stop being dispatched to it."""
        await record_models(provider.id, ["old-model"])
        await record_models(provider.id, ["new-model"])
        assert await _models_of(session, provider.id) == {"new-model"}

    async def test_clear_models_removes_them(self, session, provider) -> None:
        await record_models(provider.id, ["llama-3-70b"])
        await clear_models(provider.id)
        assert await _models_of(session, provider.id) == set()

    async def test_mark_provider_seen_makes_the_node_look_live(self, session) -> None:
        """Selection filters on presence; a tunnel that doesn't stamp it is invisible."""
        # Own the id rather than reading it back off a committed instance: commit()
        # expires the object, and touching it from sync context trips a lazy load.
        pid = uuid.uuid4()
        session.add(Provider(id=pid, name="gpu-farm", wallet_address=wallet_address()))
        await session.commit()

        # No read between the commit and this call: an open read transaction here blocks
        # mark_provider_seen's write on its own connection, and SQLite deadlocks.
        await mark_provider_seen(pid)

        session.expire_all()
        last_seen = await session.scalar(select(Provider.last_seen).where(Provider.id == pid))
        assert last_seen is not None
        # Checked with the same predicate node selection uses, not a copy of its logic.
        assert is_connected(
            Provider(last_seen=last_seen),
            datetime.now(UTC),
            get_settings().connection_timeout_seconds,
        )


# ── The declared list is untrusted input ────────────────────────────────────────


class TestModelListIsUntrustedInput:
    """A node names its own models. Nothing stops a compromised one from lying."""

    def test_the_list_is_bounded(self) -> None:
        assert len(_clean_models([f"m{i}" for i in range(500)])) == 64

    def test_overlong_names_are_dropped(self) -> None:
        assert _clean_models(["x" * 129, "ok"]) == ["ok"]

    @pytest.mark.parametrize("junk", ["not-a-list", None, 42, {"a": 1}])
    def test_a_non_list_yields_nothing(self, junk) -> None:
        assert _clean_models(junk) == []

    def test_non_strings_and_blanks_are_dropped(self) -> None:
        assert _clean_models(["ok", 1, None, "", "   ", {"x": 1}]) == ["ok"]

    def test_duplicates_collapse(self) -> None:
        """The table is unique on (provider, model); duplicates would fail the insert."""
        assert _clean_models(["a", "a", "b"]) == ["a", "b"]
