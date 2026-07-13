"""Reconciliation (Session 13) — the last line of defence.

On a schedule, compare what the chain says against what the off-chain ledger believes. If they
diverge by a single unit, we must *know* — a silent gap between on-chain and off-chain money is
exactly the failure a decentralised settlement layer cannot tolerate.

Two families of check, both derived so that a healthy system reconciles to **zero**:

* **Developer escrow** — ``balanceOf(wallet)`` on-chain must equal
  ``developer_free + escrow_held + consumed − confirmed_debits`` off-chain. Every term cancels
  to ``deposits − withdrawals − debits`` (the chain's own definition), so any nonzero delta means
  a missed event, a bad posting, or an over-debit.
* **Provider payout** — the ``Settled`` amounts we *recorded* (confirmed ``ProviderSettlement``)
  must match the ``Settled`` events actually *observed* on-chain, and must never exceed what the
  provider earned off-chain (the over-pay guard).

The divergence count is published as a Prometheus gauge; a nonzero value trips an Alertmanager
rule (the same delivery path proven in Session 12.7).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from loguru import logger
from prometheus_client import Gauge
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chain.client import ChainClient, ChainError
from app.chain.units import to_units
from app.ledger import account_balance
from app.models import (
    ChainEvent,
    ChainSettlement,
    ChainTxKind,
    ChainTxStatus,
    Developer,
    LedgerAccount,
    LedgerDirection,
    LedgerEntry,
    Provider,
    ProviderSettlement,
)

# Published to the default registry the scheduler already exposes to Prometheus (12.7).
CHAIN_DIVERGENCE = Gauge(
    "gridix_chain_ledger_divergence",
    "Number of on-chain vs off-chain ledger divergences found by the last reconciliation.",
)
CHAIN_RECONCILE_TS = Gauge(
    "gridix_chain_reconcile_timestamp",
    "Unix time of the last successful reconciliation run.",
)


@dataclass(frozen=True)
class Divergence:
    kind: str  # developer_escrow | provider_settled | provider_overpay
    subject: str  # wallet or provider id
    expected: int  # units the off-chain ledger implies
    actual: int  # units the chain reports
    severity: str = "critical"

    @property
    def delta(self) -> int:
        return self.actual - self.expected


class Reconciler:
    def __init__(
        self,
        client: ChainClient,
        factory: async_sessionmaker[AsyncSession],
        *,
        usdc_decimals: int,
    ) -> None:
        self._client = client
        self._factory = factory
        self._decimals = usdc_decimals

    async def run(self) -> list[Divergence]:
        """Reconcile and publish the divergence gauge. Returns divergences found (empty=clean)."""
        try:
            async with self._factory() as session:
                divergences = await self._reconcile(session)
        except ChainError as exc:
            logger.warning("reconciliation chain error (will retry next cycle): {}", exc)
            return []
        CHAIN_DIVERGENCE.set(len(divergences))
        CHAIN_RECONCILE_TS.set_to_current_time()
        if divergences:
            for d in divergences:
                logger.error(
                    "RECONCILE DIVERGENCE {} {}: expected {} units, chain has {} (delta {})",
                    d.kind,
                    d.subject,
                    d.expected,
                    d.actual,
                    d.delta,
                )
        else:
            logger.info("reconciliation clean: on-chain and ledger agree (zero divergence)")
        return divergences

    async def _reconcile(self, session: AsyncSession) -> list[Divergence]:
        out: list[Divergence] = []
        out.extend(await self._check_developers(session))
        out.extend(await self._check_providers(session))
        return out

    # ── developer escrow ─────────────────────────────────────────────────────────────────
    async def _check_developers(self, session: AsyncSession) -> list[Divergence]:
        devs = list(
            await session.scalars(select(Developer).where(Developer.wallet_address.is_not(None)))
        )
        settled = await self._settled_units_by_dev(session)
        debited = await self._confirmed_debited_by_dev(session)
        out: list[Divergence] = []
        for dev in devs:
            free = await account_balance(session, LedgerAccount.developer, dev.id)
            held = await account_balance(session, LedgerAccount.escrow, dev.id)
            expected = (
                to_units(free + held, self._decimals)
                + settled.get(dev.id, 0)
                - debited.get(dev.id, 0)
            )
            actual = await self._client.escrow_balance_of(dev.wallet_address)
            if actual != expected:
                out.append(Divergence("developer_escrow", dev.wallet_address, expected, actual))
        return out

    # ── provider payout ──────────────────────────────────────────────────────────────────
    async def _check_providers(self, session: AsyncSession) -> list[Divergence]:
        provs = list(
            await session.scalars(select(Provider).where(Provider.wallet_address.is_not(None)))
        )
        recorded = await self._recorded_settled_by_provider(session)
        observed = await self._observed_settled_by_wallet(session)
        earned = await self._earned_units_by_provider(session)
        out: list[Divergence] = []
        for prov in provs:
            wallet = prov.wallet_address.lower()
            rec = recorded.get(prov.id, 0)
            obs = observed.get(wallet, 0)
            if rec != obs:
                out.append(Divergence("provider_settled", wallet, rec, obs))
            if rec > earned.get(prov.id, 0):
                # We settled more on-chain than the provider ever earned — over-pay.
                out.append(Divergence("provider_overpay", wallet, earned.get(prov.id, 0), rec))
        return out

    # ── helpers ──────────────────────────────────────────────────────────────────────────
    async def _settled_units_by_dev(self, session: AsyncSession) -> dict:
        from sqlalchemy import func

        rows = await session.execute(
            select(LedgerEntry.account_ref, func.sum(LedgerEntry.amount))
            .where(
                LedgerEntry.account == LedgerAccount.escrow,
                LedgerEntry.direction == LedgerDirection.debit,
                LedgerEntry.reason == "settle",
                LedgerEntry.account_ref.is_not(None),
            )
            .group_by(LedgerEntry.account_ref)
        )
        return {ref: to_units(Decimal(str(total or 0)), self._decimals) for ref, total in rows}

    async def _confirmed_debited_by_dev(self, session: AsyncSession) -> dict:
        rows = list(
            await session.scalars(
                select(ChainSettlement).where(
                    ChainSettlement.kind == ChainTxKind.debit,
                    ChainSettlement.status == ChainTxStatus.confirmed,
                )
            )
        )
        wallet_to_dev = {
            w.lower(): pid
            for w, pid in await session.execute(
                select(Developer.wallet_address, Developer.id).where(
                    Developer.wallet_address.is_not(None)
                )
            )
        }
        out: dict = {}
        for row in rows:
            dev_id = wallet_to_dev.get(str(row.payload["developer"]).lower())
            if dev_id is not None:
                out[dev_id] = out.get(dev_id, 0) + int(row.payload["amount"])
        return out

    async def _recorded_settled_by_provider(self, session: AsyncSession) -> dict:
        from sqlalchemy import func

        rows = await session.execute(
            select(ProviderSettlement.provider_id, func.sum(ProviderSettlement.amount_units))
            .join(ChainSettlement, ChainSettlement.id == ProviderSettlement.settlement_id)
            .where(ChainSettlement.status == ChainTxStatus.confirmed)
            .group_by(ProviderSettlement.provider_id)
        )
        return {pid: int(total or 0) for pid, total in rows}

    async def _observed_settled_by_wallet(self, session: AsyncSession) -> dict:
        rows = list(
            await session.scalars(
                select(ChainEvent).where(
                    ChainEvent.event_name == "Settled", ChainEvent.confirmed.is_(True)
                )
            )
        )
        out: dict = {}
        for ev in rows:
            wallet = str(ev.args["provider"]).lower()
            out[wallet] = out.get(wallet, 0) + int(ev.args["amount"])
        return out

    async def _earned_units_by_provider(self, session: AsyncSession) -> dict:
        from sqlalchemy import case, func

        debit = func.sum(
            case((LedgerEntry.direction == LedgerDirection.debit, LedgerEntry.amount), else_=0)
        )
        credit = func.sum(
            case((LedgerEntry.direction == LedgerDirection.credit, LedgerEntry.amount), else_=0)
        )
        rows = await session.execute(
            select(LedgerEntry.account_ref, credit, debit)
            .where(
                LedgerEntry.account == LedgerAccount.provider,
                LedgerEntry.account_ref.is_not(None),
            )
            .group_by(LedgerEntry.account_ref)
        )
        return {
            ref: to_units(Decimal(str(cr or 0)) - Decimal(str(dr or 0)), self._decimals)
            for ref, cr, dr in rows
        }
