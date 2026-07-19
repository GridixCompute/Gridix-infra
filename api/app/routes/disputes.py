"""Dispute endpoints (Session 10.2/10.4): a provider sees why it was slashed and contests.

Every slash links reproducible evidence; a provider can pull the full evidence set that
triggered it and open a contest within the window.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import InternalDep, ProviderPrincipalDep, SessionDep
from app.disputes import contest_dispute, resolve_dispute
from app.models import Dispute, DisputeState
from app.schemas import DisputeResponse, DisputeRuling

router = APIRouter(tags=["disputes"])


async def _owned_dispute(session: SessionDep, provider_id: uuid.UUID, dispute_id: uuid.UUID):
    dispute = await session.get(Dispute, dispute_id)
    if dispute is None or dispute.provider_id != provider_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found.")
    return dispute


@router.get("/disputes/me", response_model=list[DisputeResponse])
async def my_disputes(provider: ProviderPrincipalDep, session: SessionDep) -> list[Dispute]:
    """List the calling provider's disputes, newest first."""
    rows = await session.scalars(
        select(Dispute)
        .where(Dispute.provider_id == provider.id)
        .order_by(Dispute.created_at.desc())
    )
    return list(rows)


@router.get("/disputes/review-queue", response_model=list[DisputeResponse])
async def review_queue(_: InternalDep, session: SessionDep) -> list[Dispute]:
    """Operator view: disputes awaiting manual adjudication, oldest first (10.4).

    Declared before ``/disputes/{dispute_id}`` so the literal path isn't captured as an id.
    """
    rows = await session.scalars(
        select(Dispute)
        .where(Dispute.state == DisputeState.under_review)
        .order_by(Dispute.created_at.asc())
    )
    return list(rows)


@router.get("/disputes/{dispute_id}", response_model=DisputeResponse)
async def get_dispute(
    dispute_id: uuid.UUID, provider: ProviderPrincipalDep, session: SessionDep
) -> Dispute:
    """Return one of the provider's disputes with the full evidence that triggered it."""
    return await _owned_dispute(session, provider.id, dispute_id)


@router.post("/disputes/{dispute_id}/contest", response_model=DisputeResponse)
async def contest(
    dispute_id: uuid.UUID, provider: ProviderPrincipalDep, session: SessionDep
) -> Dispute:
    """Contest an open slash within its window → moves it to review."""
    dispute = await _owned_dispute(session, provider.id, dispute_id)
    if dispute.state is not DisputeState.open:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Dispute is no longer open."
        )
    if not await contest_dispute(session, dispute):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Dispute contest window has closed."
        )
    return dispute


@router.post("/disputes/{dispute_id}/rule", response_model=DisputeResponse)
async def rule_on_dispute(
    dispute_id: uuid.UUID, body: DisputeRuling, _: InternalDep, session: SessionDep
) -> Dispute:
    """Operator records a ruling on an under-review dispute, with an audit-logged reason."""
    dispute = await session.get(Dispute, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found.")
    if dispute.state in (DisputeState.upheld, DisputeState.overturned):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Dispute already resolved."
        )
    await resolve_dispute(session, dispute, upheld=body.upheld, ruling_reason=body.reason)
    return dispute
