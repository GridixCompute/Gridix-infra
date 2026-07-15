"""Developer billing endpoints (Session 10): an auditable view of the ledger.

The double-entry ledger is the source of truth. These endpoints expose the developer's
own money movements — escrow holds, settlements, refunds, data charges — and authoritative
period totals, so the UI can show exact figures and reconcile against the on-chain escrow.
"""

from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select

from app.deps import DeveloperDep, SessionDep
from app.ledger import account_balance
from app.models import Job, LedgerAccount, LedgerDirection, LedgerEntry
from app.schemas import BillingLedgerEntry, BillingSummary

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/ledger", response_model=list[BillingLedgerEntry])
async def my_ledger(
    developer: DeveloperDep,
    session: SessionDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[LedgerEntry]:
    """Every ledger leg across this developer's jobs, newest first.

    Ordered by group so the two (or more) legs of a transaction stay adjacent.
    """
    rows = await session.scalars(
        select(LedgerEntry)
        .join(Job, LedgerEntry.job_id == Job.id)
        .where(Job.developer_id == developer.id)
        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.entry_group)
        .limit(limit)
        .offset(offset)
    )
    return list(rows)


@router.get("/summary", response_model=BillingSummary)
async def my_summary(developer: DeveloperDep, session: SessionDep) -> BillingSummary:
    """Authoritative period totals derived from the developer's ledger."""
    dev_jobs = select(Job.id).where(Job.developer_id == developer.id).scalar_subquery()

    async def total(*conditions) -> float:
        q = select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.job_id.in_(dev_jobs), *conditions
        )
        return float(await session.scalar(q) or 0)

    provider_paid = await total(
        LedgerEntry.account == LedgerAccount.provider,
        LedgerEntry.direction == LedgerDirection.credit,
        LedgerEntry.reason == "settle",
    )
    protocol_fees = await total(
        LedgerEntry.account == LedgerAccount.protocol,
        LedgerEntry.direction == LedgerDirection.credit,
        LedgerEntry.reason == "settle",
    )
    data_costs = await total(
        LedgerEntry.account == LedgerAccount.developer,
        LedgerEntry.direction == LedgerDirection.debit,
        LedgerEntry.reason == "data_cost",
    )
    total_refunded = await total(
        LedgerEntry.direction == LedgerDirection.credit,
        LedgerEntry.reason == "refund",
    )
    total_escrowed = await total(
        LedgerEntry.direction == LedgerDirection.debit,
        LedgerEntry.reason == "escrow_hold",
    )

    held = await account_balance(session, LedgerAccount.escrow, developer.id)

    job_count = (
        await session.scalar(
            select(func.count(func.distinct(LedgerEntry.job_id))).where(
                LedgerEntry.job_id.in_(dev_jobs)
            )
        )
        or 0
    )

    # Every one of the developer's transaction groups must balance (debit == credit).
    debit = func.sum(
        case((LedgerEntry.direction == LedgerDirection.debit, LedgerEntry.amount), else_=0)
    )
    credit = func.sum(
        case((LedgerEntry.direction == LedgerDirection.credit, LedgerEntry.amount), else_=0)
    )
    groups = await session.execute(
        select(LedgerEntry.entry_group, debit, credit)
        .where(LedgerEntry.job_id.in_(dev_jobs))
        .group_by(LedgerEntry.entry_group)
    )
    balanced = all(Decimal(str(d or 0)) == Decimal(str(c or 0)) for _, d, c in groups)

    return BillingSummary(
        total_spent=provider_paid + protocol_fees + data_costs,
        provider_paid=provider_paid,
        protocol_fees=protocol_fees,
        data_costs=data_costs,
        total_refunded=total_refunded,
        total_held=float(held),
        total_escrowed=total_escrowed,
        job_count=int(job_count),
        balanced=balanced,
    )
