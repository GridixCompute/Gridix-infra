"""Inference dispatch: node selection rules and sending work down a tunnel.

The placement rules here are not new policy — they are `matcher.py`'s, re-proven from the
new side. matcher.py is on the delete list, and it holds the only enforcement that
confidential work runs on attested hardware (`matcher.py:87`) and that under-staked
providers get nothing (`matcher.py:135-141`). If those tests only ever existed against the
matcher, deleting it would take the guarantees with it and nothing would go red.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.config import get_settings
from app.dispatch import (
    DispatchError,
    NoNodeAvailableError,
    dispatch,
    eligible_nodes,
    select_node,
)
from app.ledger import deposit_stake
from app.models import DataTier, Provider, ProviderModel
from app.relay_client import RelayUnavailableError

MODEL = "llama-3-70b"
NOW = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)


async def make_node(
    session,
    *,
    models: tuple[str, ...] = (MODEL,),
    stake: int = 1000,
    tee: bool = False,
    enabled: bool = True,
    degraded: bool = False,
    last_seen: datetime | None = NOW,
) -> Provider:
    """A provider with a live tunnel, staked and serving ``models`` by default."""
    provider = Provider(
        name=f"node-{uuid.uuid4().hex[:6]}",
        enabled=enabled,
        degraded=degraded,
        tee_attested=tee,
        last_seen=last_seen,
        connected_at=last_seen,
    )
    session.add(provider)
    await session.flush()
    session.add_all(ProviderModel(provider_id=provider.id, model=m) for m in models)
    if stake:
        await deposit_stake(session, provider.id, Decimal(stake))
    await session.commit()
    return provider


async def _eligible(session, **kw) -> list:
    return await eligible_nodes(
        session, model=kw.pop("model", MODEL), now=kw.pop("now", NOW), settings=get_settings(), **kw
    )


class TestSelection:
    async def test_picks_a_connected_node_that_serves_the_model(self, session) -> None:
        provider = await make_node(session)
        chosen = await select_node(session, model=MODEL, now=NOW, settings=get_settings())
        assert chosen == provider.id

    async def test_ignores_nodes_that_do_not_serve_the_model(self, session) -> None:
        await make_node(session, models=("stable-diffusion-xl",))
        with pytest.raises(NoNodeAvailableError):
            await select_node(session, model=MODEL, now=NOW, settings=get_settings())

    async def test_a_node_can_serve_several_models(self, session) -> None:
        provider = await make_node(session, models=(MODEL, "stable-diffusion-xl"))
        for model in (MODEL, "stable-diffusion-xl"):
            assert (
                await select_node(session, model=model, now=NOW, settings=get_settings())
                == provider.id
            )

    async def test_no_nodes_at_all_raises(self, session) -> None:
        with pytest.raises(NoNodeAvailableError):
            await select_node(session, model=MODEL, now=NOW, settings=get_settings())


class TestDeadNodesAreNotSelected:
    async def test_a_silent_node_is_not_dispatchable(self, session) -> None:
        """Presence ages out: the tunnel died without a clean disconnect."""
        stale = NOW - timedelta(seconds=get_settings().connection_timeout_seconds + 60)
        await make_node(session, last_seen=stale)
        assert await _eligible(session) == []

    async def test_a_node_that_never_connected_is_not_dispatchable(self, session) -> None:
        await make_node(session, last_seen=None)
        assert await _eligible(session) == []

    async def test_disabled_and_degraded_nodes_are_skipped(self, session) -> None:
        await make_node(session, enabled=False)
        await make_node(session, degraded=True)
        assert await _eligible(session) == []


class TestPlacementRulesMovedFromTheMatcher:
    """These are matcher.py's guarantees, proven against the dispatcher."""

    async def test_confidential_work_never_lands_on_unattested_hardware(self, session) -> None:
        """matcher.py:87 is the only placement gate for this today. If the control did
        not move here, deleting the matcher would silently allow it."""
        await make_node(session, tee=False)
        with pytest.raises(NoNodeAvailableError):
            await select_node(
                session,
                model=MODEL,
                now=NOW,
                settings=get_settings(),
                data_tier=DataTier.confidential_tee,
            )

    async def test_confidential_work_lands_on_attested_hardware(self, session) -> None:
        attested = await make_node(session, tee=True)
        chosen = await select_node(
            session,
            model=MODEL,
            now=NOW,
            settings=get_settings(),
            data_tier=DataTier.confidential_tee,
        )
        assert chosen == attested.id

    async def test_confidential_work_prefers_the_attested_node_over_a_plain_one(
        self, session
    ) -> None:
        await make_node(session, tee=False)
        attested = await make_node(session, tee=True)
        chosen = await select_node(
            session,
            model=MODEL,
            now=NOW,
            settings=get_settings(),
            data_tier=DataTier.confidential_tee,
        )
        assert chosen == attested.id

    async def test_public_work_still_runs_anywhere(self, session) -> None:
        provider = await make_node(session, tee=False)
        chosen = await select_node(session, model=MODEL, now=NOW, settings=get_settings())
        assert chosen == provider.id

    async def test_an_understaked_node_gets_no_work(self, session) -> None:
        """Stake is the collateral slashing bites into. Without this gate, staking
        stops gating anything and a canary catch has nothing to take."""
        await make_node(session, stake=0)
        assert await _eligible(session) == []

    async def test_a_node_below_the_minimum_gets_no_work(self, session) -> None:
        await make_node(session, stake=get_settings().min_provider_stake - 1)
        assert await _eligible(session) == []

    async def test_a_node_at_the_minimum_is_eligible(self, session) -> None:
        provider = await make_node(session, stake=get_settings().min_provider_stake)
        assert [c.provider_id for c in await _eligible(session)] == [provider.id]


class TestDispatch:
    async def test_sends_the_request_and_returns_the_reply(self) -> None:
        provider_id = uuid.uuid4()
        with patch(
            "app.dispatch.call_provider",
            new=AsyncMock(return_value={"status": 200, "payload": {"text": "hello"}}),
        ) as call:
            result = await dispatch(
                provider_id, method="infer", payload={"prompt": "hi"}, settings=get_settings()
            )
        assert result == {"text": "hello"}
        assert call.await_args.kwargs["method"] == "infer"
        assert call.await_args.kwargs["payload"] == {"prompt": "hi"}

    async def test_an_unreachable_node_is_a_clean_error_not_a_crash(self) -> None:
        """The node dropped between selection and dispatch; callers may try another."""
        with (
            patch(
                "app.dispatch.call_provider",
                new=AsyncMock(side_effect=RelayUnavailableError("provider not connected")),
            ),
            pytest.raises(DispatchError),
        ):
            await dispatch(uuid.uuid4(), method="infer", payload={}, settings=get_settings())

    async def test_a_node_error_surfaces_as_a_dispatch_error(self) -> None:
        with (
            patch(
                "app.dispatch.call_provider",
                new=AsyncMock(return_value={"status": 500, "payload": {"detail": "cuda oom"}}),
            ),
            pytest.raises(DispatchError),
        ):
            await dispatch(uuid.uuid4(), method="infer", payload={}, settings=get_settings())
