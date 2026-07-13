"""Idempotent settlement engine (Session 13).

Provider earnings accumulate off-chain in the ledger. This engine periodically pushes the
*aggregate* out to ``GridixStaking.settleBatch`` so providers can withdraw on-chain. Two hard
requirements shape the design:

**No double-pay across a crash.** Before any broadcast, the batch is durably recorded: a
``ChainSettlement`` row (with a reserved nonce) plus one ``ProviderSettlement`` row per payee.
Those rows *reserve* the earnings — the next cycle subtracts them, so a crash between "record"
and "confirm" can never re-select the same earnings into a second batch. Recovery re-checks the
existing row's receipt instead of building a new one, and a re-broadcast reuses the same reserved
nonce, so the chain admits at most one tx. A reverted tx *releases* its reservation (rows
deleted) so the earnings settle in a later batch.

**Trigger (chosen & documented).** A batch fires when total unsettled earnings reach
``settlement_threshold_usdc`` (fill the batch → amortise gas) OR when ``settlement_interval``
elapses since the last batch (a floor so small balances don't wait forever) — whichever first.

Nonces are reserved monotonically from the coordinator's pending count, persisted on the row, so
a stuck tx is replaced at its own nonce rather than ever duplicated.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from loguru import logger
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chain.client import ChainClient, ChainError
from app.chain.units import to_units
from app.models import (
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

_LIVE = (ChainTxStatus.pending, ChainTxStatus.submitted, ChainTxStatus.confirmed)


@dataclass
class CycleResult:
    """What one engine tick did — surfaced for metrics, logs, and tests."""

    recovered: int = 0  # in-flight rows advanced (confirmed/failed/re-sent)
    confirmed: int = 0
    failed: int = 0
    batched: int = 0  # providers paid in a new batch this tick
    batch_tx: str | None = None
    debited: int = 0  # developers debited on-chain this tick
    skipped_no_wallet: list[str] = field(default_factory=list)


class SettlementEngine:
    def __init__(
        self,
        client: ChainClient,
        factory: async_sessionmaker[AsyncSession],
        *,
        usdc_decimals: int,
        confirmations: int,
        threshold_usdc: Decimal,
        interval_seconds: float,
        clock=None,
    ) -> None:
        self._client = client
        self._factory = factory
        self._decimals = usdc_decimals
        self._confirmations = confirmations
        self._threshold_units = to_units(threshold_usdc, usdc_decimals)
        self._interval = interval_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._last_batch_at: datetime | None = None

    # ── public entry point (called by the scheduler loop) ────────────────────────────────
    async def tick(self, *, force: bool = False) -> CycleResult:
        """Recover in-flight settlements, then maybe start a new batch. Never raises upward —
        a chain outage backs off and the durable state resumes next tick."""
        result = CycleResult()
        try:
            # Drain anything in flight first (confirm/fail/re-broadcast a stuck tx).
            async with self._factory() as session:
                await self._recover(session, result)
                await session.commit()
            # Record new outbound intent DURABLY (committed) before any broadcast.
            async with self._factory() as session:
                await self._maybe_batch(session, result, force=force)
                await session.commit()
            async with self._factory() as session:
                await self._maybe_debit(session, result, force=force)
                await session.commit()
            # Broadcast the freshly-recorded pending rows. If this throws, the rows survive as
            # `pending` and the next tick's recovery re-broadcasts them — no lost or double pay.
            async with self._factory() as session:
                await self._recover(session, result)
                await session.commit()
        except ChainError as exc:
            logger.warning("settlement tick chain error (will retry): {}", exc)
        except Exception:
            logger.exception("settlement tick failed")
        return result

    # ── recovery of in-flight rows ───────────────────────────────────────────────────────
    async def _recover(self, session: AsyncSession, result: CycleResult) -> None:
        rows = list(
            await session.scalars(
                select(ChainSettlement)
                .where(ChainSettlement.status.in_((ChainTxStatus.pending, ChainTxStatus.submitted)))
                .order_by(ChainSettlement.nonce.asc())
            )
        )
        latest = await self._client.latest_block() if rows else 0
        for row in rows:
            # A row stuck in `pending` means we crashed before/at broadcast. Re-broadcast at the
            # SAME reserved nonce — the chain admits at most one tx per nonce, so this can't double.
            if row.status is ChainTxStatus.pending or row.tx_hash is None:
                try:
                    await self._broadcast(row)
                    row.status = ChainTxStatus.submitted
                    row.submitted_at = self._clock()
                    result.recovered += 1
                    if row.kind is ChainTxKind.settle_batch:
                        result.batch_tx = row.tx_hash
                except ChainError as exc:
                    logger.warning("re-broadcast of {} failed: {}", row.batch_key, exc)
                    continue
            receipt = await self._client.get_receipt(row.tx_hash) if row.tx_hash else None
            if receipt is None:
                continue  # not mined yet (or stuck) — try again next tick
            if latest - receipt.block_number + 1 < self._confirmations:
                continue  # mined but not yet final — wait for confirmations (reorg guard)
            if receipt.status == 1:
                row.status = ChainTxStatus.confirmed
                row.block_number = receipt.block_number
                row.confirmed_at = self._clock()
                result.confirmed += 1
                logger.info(
                    "settlement {} confirmed in block {}", row.batch_key, receipt.block_number
                )
            else:
                # Reverted on-chain → release the reservation so the earnings settle in a later
                # batch. Deleting the ProviderSettlement rows makes them "unsettled" again.
                row.status = ChainTxStatus.failed
                row.error = "reverted on-chain"
                await session.execute(
                    ProviderSettlement.__table__.delete().where(
                        ProviderSettlement.settlement_id == row.id
                    )
                )
                result.failed += 1
                logger.warning("settlement {} reverted; reservation released", row.batch_key)

    # ── build & broadcast a new batch ────────────────────────────────────────────────────
    async def _maybe_batch(
        self, session: AsyncSession, result: CycleResult, *, force: bool
    ) -> None:
        # If anything is still in flight, don't start a second batch — recovery must drain first
        # so nonces stay ordered and we never race two settleBatch txs.
        if await self._inflight(session):
            return

        unsettled = await self._unsettled(session, result)
        total = sum(units for _, units in unsettled.values())
        if total <= 0:
            return
        due = force or total >= self._threshold_units or self._interval_elapsed()
        if not due:
            return

        providers = sorted(unsettled.items(), key=lambda kv: str(kv[0]))
        payees = [wallet for _, (wallet, _u) in providers]
        amounts = [units for _, (_w, units) in providers]

        cycle = uuid.uuid4().hex[:16]
        base_nonce = await self._reserve_base_nonce(session)

        # 1) fund the pool for exactly the shortfall (over-funding would leak coordinator USDC).
        pool = await self._client.settlement_pool()
        shortfall = max(0, total - pool)
        deposit_row: ChainSettlement | None = None
        if shortfall > 0:
            deposit_row = ChainSettlement(
                kind=ChainTxKind.deposit_settlement,
                status=ChainTxStatus.pending,
                batch_key=f"deposit:{cycle}",
                nonce=base_nonce,
                payload={"amount": shortfall},
            )
            session.add(deposit_row)

        # 2) the settleBatch itself, with per-provider reservation rows.
        settle_nonce = base_nonce + (1 if shortfall > 0 else 0)
        settle_row = ChainSettlement(
            kind=ChainTxKind.settle_batch,
            status=ChainTxStatus.pending,
            batch_key=f"settle:{cycle}",
            nonce=settle_nonce,
            payload={"payees": [[w, u] for w, u in zip(payees, amounts, strict=True)]},
        )
        session.add(settle_row)
        await session.flush()
        for provider_id, (_wallet, units) in providers:
            session.add(
                ProviderSettlement(
                    provider_id=provider_id, settlement_id=settle_row.id, amount_units=units
                )
            )
        # The caller commits right after this — the reservation is the idempotency point of no
        # return. Broadcasting happens in the following recovery pass, off this committed state.
        self._last_batch_at = self._clock()
        result.batched = len(providers)
        logger.info(
            "settlement batch {} recorded: {} providers, {} units (nonce {})",
            cycle,
            len(providers),
            total,
            settle_nonce,
        )

    # ── developer escrow debit (aggregate consumed → treasury, on-chain) ─────────────────
    async def _maybe_debit(
        self, session: AsyncSession, result: CycleResult, *, force: bool
    ) -> None:
        """Debit each developer's on-chain escrow for what their jobs have consumed off-chain.

        ``consumed_not_debited = settled_units(dev) − live_debit_units(dev)`` — the amount moved
        escrow→provider/protocol off-chain that hasn't yet been pulled on-chain to the treasury.
        Recording the debit row (with reserved nonce) before broadcast makes it idempotent the
        same way settleBatch is: a crash can't double-debit because the live row is subtracted."""
        inflight = await self._inflight(session)
        if inflight:
            return
        settled = await self._settled_units_by_dev(session)
        debited = await self._onchain_debited_by_dev(session)
        wallets = await self._dev_wallets(session, list(settled.keys()))
        due = force or self._interval_elapsed()
        if not due:
            return
        base_nonce = await self._reserve_base_nonce(session)
        offset = 0
        for dev_id, settled_units in sorted(settled.items(), key=lambda kv: str(kv[0])):
            owed = settled_units - debited.get(dev_id, 0)
            wallet = wallets.get(dev_id)
            if owed <= 0 or not wallet:
                continue
            row = ChainSettlement(
                kind=ChainTxKind.debit,
                status=ChainTxStatus.pending,
                batch_key=f"debit:{dev_id}:{settled_units}",
                nonce=base_nonce + offset,
                payload={"developer": wallet, "amount": owed},
            )
            session.add(row)
            await session.flush()
            offset += 1
            result.debited += 1

    async def _settled_units_by_dev(self, session: AsyncSession) -> dict[uuid.UUID, int]:
        """Units consumed per developer = escrow debits with reason 'settle', by dev ref."""
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

    async def _onchain_debited_by_dev(self, session: AsyncSession) -> dict[uuid.UUID, int]:
        """Units already debited on-chain per developer, from live debit rows' payloads."""
        rows = list(
            await session.scalars(
                select(ChainSettlement).where(
                    ChainSettlement.kind == ChainTxKind.debit,
                    ChainSettlement.status.in_(_LIVE),
                )
            )
        )
        out: dict[uuid.UUID, int] = {}
        wallet_to_dev = await self._wallet_to_dev(session)
        for row in rows:
            wallet = str(row.payload["developer"]).lower()
            dev_id = wallet_to_dev.get(wallet)
            if dev_id is not None:
                out[dev_id] = out.get(dev_id, 0) + int(row.payload["amount"])
        return out

    async def _dev_wallets(
        self, session: AsyncSession, dev_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        if not dev_ids:
            return {}
        rows = await session.execute(
            select(Developer.id, Developer.wallet_address).where(Developer.id.in_(dev_ids))
        )
        return dict(rows.all())

    async def _wallet_to_dev(self, session: AsyncSession) -> dict[str, uuid.UUID]:
        rows = await session.execute(
            select(Developer.wallet_address, Developer.id).where(
                Developer.wallet_address.is_not(None)
            )
        )
        return {w.lower(): pid for w, pid in rows}

    async def _inflight(self, session: AsyncSession) -> int:
        return await session.scalar(
            select(func.count())
            .select_from(ChainSettlement)
            .where(ChainSettlement.status.in_((ChainTxStatus.pending, ChainTxStatus.submitted)))
        )

    async def _broadcast(self, row: ChainSettlement) -> None:
        if row.kind is ChainTxKind.settle_batch:
            payees = [w for w, _ in row.payload["payees"]]
            amounts = [int(u) for _, u in row.payload["payees"]]
            row.tx_hash = await self._client.send_settle_batch(payees, amounts, row.nonce)
        elif row.kind is ChainTxKind.deposit_settlement:
            row.tx_hash = await self._client.send_deposit_settlement(
                int(row.payload["amount"]), row.nonce
            )
        elif row.kind is ChainTxKind.debit:
            row.tx_hash = await self._client.send_debit(
                row.payload["developer"], int(row.payload["amount"]), row.nonce
            )

    # ── helpers ──────────────────────────────────────────────────────────────────────────
    async def _unsettled(
        self, session: AsyncSession, result: CycleResult
    ) -> dict[uuid.UUID, tuple[str, int]]:
        """Return {provider_id: (wallet, unsettled_units)} for providers owed on-chain payment.

        unsettled = earned_off_chain − already_reserved_or_settled. Providers with no linked
        wallet are skipped (recorded on the result) — we can't pay an address we don't have.
        """
        earned = await self._earned_by_provider(session)
        reserved = await self._reserved_by_provider(session)
        wallets: dict[uuid.UUID, str | None] = {}
        if earned:
            rows = await session.execute(
                select(Provider.id, Provider.wallet_address).where(Provider.id.in_(earned.keys()))
            )
            wallets = dict(rows.all())
        out: dict[uuid.UUID, tuple[str, int]] = {}
        for pid, earned_dec in earned.items():
            units = to_units(earned_dec, self._decimals) - reserved.get(pid, 0)
            if units <= 0:
                continue
            wallet = wallets.get(pid)
            if not wallet:
                result.skipped_no_wallet.append(str(pid))
                continue
            out[pid] = (wallet, units)
        return out

    async def _earned_by_provider(self, session: AsyncSession) -> dict[uuid.UUID, Decimal]:
        """Off-chain earnings (credits − debits) per provider ref, portable across SQLite/PG."""
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
        out: dict[uuid.UUID, Decimal] = {}
        for ref, cr, dr in rows:
            bal = Decimal(str(cr or 0)) - Decimal(str(dr or 0))
            if bal > 0:
                out[ref] = bal
        return out

    async def _reserved_by_provider(self, session: AsyncSession) -> dict[uuid.UUID, int]:
        rows = await session.execute(
            select(ProviderSettlement.provider_id, func.sum(ProviderSettlement.amount_units))
            .join(ChainSettlement, ChainSettlement.id == ProviderSettlement.settlement_id)
            .where(ChainSettlement.status.in_(_LIVE))
            .group_by(ProviderSettlement.provider_id)
        )
        return {pid: int(total or 0) for pid, total in rows}

    async def _reserve_base_nonce(self, session: AsyncSession) -> int:
        """Next free nonce: max(chain pending count, our highest reserved nonce + 1)."""
        chain_nonce = await self._client.get_nonce(pending=True)
        max_row = await session.scalar(select(func.max(ChainSettlement.nonce)))
        return max(chain_nonce, (int(max_row) + 1) if max_row is not None else 0)

    def _interval_elapsed(self) -> bool:
        if self._last_batch_at is None:
            return True
        return (self._clock() - self._last_batch_at).total_seconds() >= self._interval
