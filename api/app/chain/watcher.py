"""Chain watcher (Session 13) — mirror confirmed on-chain facts into the ledger.

Watches five events across the two contracts: ``Deposited`` / ``Withdrawn`` / ``Debited``
(escrow) and ``Settled`` / ``Slashed`` (staking). Two events carry a ledger side effect:

* ``Deposited`` → credit the developer's off-chain ``developer`` balance (this is how money
  *enters* the ledger — the source of a developer's spendable balance);
* ``Withdrawn`` → debit it (the developer pulled escrow back out on-chain).

Everything else is recorded for reconciliation to read. Three correctness rules:

1. **Never trust one block.** A side effect is applied only once its block is
   ``chain_confirmations`` deep, so a shallow reorg can't move already-credited money.
2. **Reorg rollback.** Each scan re-verifies recent block hashes; if a stored event's block was
   orphaned (same number, different canonical hash), the event is dropped and — if its effect had
   been applied — reversed with a compensating (append-only, balanced) ledger posting.
3. **Exactly once.** Events dedup on ``(tx_hash, log_index)``; re-scanning is idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chain.client import ChainClient, ChainError
from app.chain.units import from_units
from app.ledger import Posting, post_transaction
from app.models import (
    ChainCursor,
    ChainEvent,
    Developer,
    LedgerAccount,
    LedgerDirection,
)

_STREAM = "chain"
_EFFECTFUL = {"Deposited", "Withdrawn"}


@dataclass
class ScanResult:
    new_events: int = 0
    confirmed: int = 0
    applied: int = 0
    orphaned: int = 0
    reversed_effects: int = 0
    reorg_depth: int = 0
    unmapped_wallets: list[str] = field(default_factory=list)


class ChainWatcher:
    def __init__(
        self,
        client: ChainClient,
        factory: async_sessionmaker[AsyncSession],
        *,
        usdc_decimals: int,
        confirmations: int,
        reorg_window: int | None = None,
        clock=None,
    ) -> None:
        self._client = client
        self._factory = factory
        self._decimals = usdc_decimals
        self._confirmations = confirmations
        # How far back to re-verify hashes each scan. Must exceed the depth we apply effects at,
        # so an orphan of an applied event is always caught.
        self._reorg_window = reorg_window if reorg_window is not None else confirmations + 2
        self._clock = clock or (lambda: datetime.now(UTC))

    async def tick(self) -> ScanResult:
        """One scan: detect reorgs, ingest new logs, then apply the newly-final ones."""
        result = ScanResult()
        try:
            async with self._factory() as session:
                await self._scan(session, result)
                await session.commit()
        except ChainError as exc:
            logger.warning("watcher tick chain error (will retry): {}", exc)
        except Exception:
            logger.exception("watcher tick failed")
        return result

    async def _scan(self, session: AsyncSession, result: ScanResult) -> None:
        latest = await self._client.latest_block()
        cursor = await session.get(ChainCursor, _STREAM)
        if cursor is None:
            cursor = ChainCursor(stream=_STREAM, last_scanned_block=0, head_block_hash=None)
            session.add(cursor)

        # 1) reorg check + orphan rollback over the trailing window.
        window_start = max(1, cursor.last_scanned_block - self._reorg_window + 1)
        await self._handle_reorg(session, window_start, latest, result)

        # 2) ingest logs from the (possibly rewound) frontier up to the latest block.
        from_block = min(cursor.last_scanned_block + 1, window_start)
        if from_block <= latest:
            for log in await self._client.get_logs(from_block, latest):
                exists = await session.scalar(
                    select(ChainEvent).where(
                        ChainEvent.tx_hash == log.tx_hash, ChainEvent.log_index == log.log_index
                    )
                )
                if exists is not None:
                    continue
                session.add(
                    ChainEvent(
                        event_name=log.event_name, tx_hash=log.tx_hash, log_index=log.log_index,
                        block_number=log.block_number, block_hash=log.block_hash,
                        address=log.address, args=log.args, confirmed=False, processed=False,
                    )
                )
                result.new_events += 1
            head = await self._client.get_block(latest)
            cursor.last_scanned_block = latest
            cursor.head_block_hash = head.hash
        await session.flush()

        # 3) apply effects for events now buried >= confirmations deep.
        await self._apply_confirmed(session, latest, result)

    async def _handle_reorg(
        self, session: AsyncSession, window_start: int, latest: int, result: ScanResult
    ) -> None:
        """Drop (and reverse) any stored event whose block was orphaned by a reorg."""
        events = list(
            await session.scalars(
                select(ChainEvent).where(ChainEvent.block_number >= window_start)
            )
        )
        if not events:
            return
        # canonical hash per block number, once.
        canonical: dict[int, str | None] = {}
        for ev in events:
            if ev.block_number not in canonical:
                try:
                    blk = await self._client.get_block(ev.block_number)
                    canonical[ev.block_number] = blk.hash if ev.block_number <= latest else None
                except ChainError:
                    canonical[ev.block_number] = None
            good = canonical[ev.block_number]
            if good == ev.block_hash:
                continue
            # orphaned: reverse its effect if applied, then delete the row.
            result.orphaned += 1
            result.reorg_depth = max(result.reorg_depth, ev.block_number)
            if ev.processed and ev.event_name in _EFFECTFUL:
                await self._reverse_effect(session, ev, result)
            await session.delete(ev)
        if result.orphaned:
            logger.warning("reorg: dropped {} orphaned event(s)", result.orphaned)

    async def _apply_confirmed(
        self, session: AsyncSession, latest: int, result: ScanResult
    ) -> None:
        events = list(
            await session.scalars(
                select(ChainEvent)
                .where(ChainEvent.processed.is_(False))
                .order_by(ChainEvent.block_number.asc(), ChainEvent.log_index.asc())
            )
        )
        for ev in events:
            if latest - ev.block_number + 1 < self._confirmations:
                continue  # not final yet
            ev.confirmed = True
            result.confirmed += 1
            if ev.event_name in _EFFECTFUL:
                applied = await self._apply_effect(session, ev, result)
                if not applied:
                    continue  # unmapped wallet — leave unprocessed? mark processed to avoid loop
            ev.processed = True
            if ev.event_name in _EFFECTFUL:
                result.applied += 1

    async def _developer_for(self, session: AsyncSession, wallet: str) -> Developer | None:
        return await session.scalar(
            select(Developer).where(Developer.wallet_address == wallet.lower())
        )

    async def _apply_effect(
        self, session: AsyncSession, ev: ChainEvent, result: ScanResult
    ) -> bool:
        wallet = str(ev.args["developer"]).lower()
        dev = await self._developer_for(session, wallet)
        if dev is None:
            # A deposit from a wallet we don't know yet — record it, don't guess an owner.
            result.unmapped_wallets.append(wallet)
            ev.processed = True  # don't retry forever; reconciliation still sees the event
            return False
        amount = from_units(int(ev.args["amount"]), self._decimals)
        if ev.event_name == "Deposited":
            await post_transaction(
                session,
                [
                    Posting(LedgerAccount.protocol, LedgerDirection.debit, amount),
                    Posting(LedgerAccount.developer, LedgerDirection.credit, amount, dev.id),
                ],
                reason="chain_deposit",
            )
        elif ev.event_name == "Withdrawn":
            await post_transaction(
                session,
                [
                    Posting(LedgerAccount.developer, LedgerDirection.debit, amount, dev.id),
                    Posting(LedgerAccount.protocol, LedgerDirection.credit, amount),
                ],
                reason="chain_withdraw",
            )
        return True

    async def _reverse_effect(
        self, session: AsyncSession, ev: ChainEvent, result: ScanResult
    ) -> None:
        """Compensate an applied effect that was orphaned (append-only, balanced)."""
        wallet = str(ev.args["developer"]).lower()
        dev = await self._developer_for(session, wallet)
        if dev is None:
            return
        amount = from_units(int(ev.args["amount"]), self._decimals)
        if ev.event_name == "Deposited":
            postings = [
                Posting(LedgerAccount.developer, LedgerDirection.debit, amount, dev.id),
                Posting(LedgerAccount.protocol, LedgerDirection.credit, amount),
            ]
        else:  # Withdrawn
            postings = [
                Posting(LedgerAccount.protocol, LedgerDirection.debit, amount),
                Posting(LedgerAccount.developer, LedgerDirection.credit, amount, dev.id),
            ]
        await post_transaction(session, postings, reason=f"reorg_reverse_{ev.event_name.lower()}")
        result.reversed_effects += 1
