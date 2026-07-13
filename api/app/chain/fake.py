"""In-memory chain simulation implementing :class:`ChainClient`.

Drives the entire hermetic test suite (and local dev with ``chain_enabled`` but no RPC). It
models exactly the behaviour the settlement engine and watcher depend on:

* explicit block production via :meth:`mine` — nothing is "confirmed" until enough blocks are
  mined on top of it, so confirmation logic is testable;
* faithful contract effects — ``settleBatch`` reverts if the pool is underfunded, ``debit``
  reverts past a developer's balance, mirroring the real contracts;
* fault injection — :meth:`fail_next_send` (broadcast failure), :meth:`hold_pending` (stuck
  tx), :meth:`force_revert`, and :meth:`reorg` (orphan the head, re-mine a different hash).

It is synchronous under the hood with ``async`` method signatures so it drops in for the real
client.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from app.chain.client import BlockRef, ChainClient, ChainError, ChainLog, Receipt

_ESCROW = "0x" + "e5".ljust(40, "0")
_STAKING = "0x" + "57".ljust(40, "0")
_COORD = "0x" + "c0".ljust(40, "0")
_TREASURY = "0x" + "77" * 20

# A queued item: (kind, tx_hash, nonce, apply). apply(num,bhash) -> (status, [(name,addr,args)]).
# nonce is None for external (non-coordinator) actions; coordinator txs mine in nonce order.
LogSpec = tuple[str, str, dict]
Apply = Callable[[int, str], "tuple[int, list[LogSpec]]"]


class FakeChain(ChainClient):
    def __init__(
        self,
        *,
        coordinator: str = _COORD,
        escrow_address: str = _ESCROW,
        staking_address: str = _STAKING,
    ) -> None:
        self._coord = coordinator.lower()
        self.escrow_address = escrow_address.lower()
        self.staking_address = staking_address.lower()
        self._logs: dict[int, list[ChainLog]] = {}
        self._receipts: dict[str, Receipt] = {}
        self._queue: list[tuple[str, str, int | None, Apply]] = []
        self._escrow_bal: dict[str, int] = defaultdict(int)
        self._earnings: dict[str, int] = defaultdict(int)
        self._pool = 0
        self._mined_nonce = 0  # next coordinator nonce eligible to mine (Ethereum ordering)
        self._seq = 0
        self._salt = 0
        self._fail_next_send = False
        self._hold_pending = False
        self._revert_kinds: set[str] = set()
        # genesis (needs _salt set above for _bhash)
        self._blocks: list[BlockRef] = [BlockRef(0, self._bhash(0), "0x" + "00" * 32)]

    # ── deterministic ids (block hashes change with salt so a re-mine differs) ───────────
    def _bhash(self, number: int) -> str:
        return "0x" + f"b{self._salt:02x}{number:062x}"[-64:]

    def _txhash(self) -> str:
        self._seq += 1
        return "0x" + f"{self._seq:064x}"

    # ── test controls ────────────────────────────────────────────────────────────────
    def fund_pool(self, amount: int) -> None:
        self._pool += amount

    def fail_next_send(self, on: bool = True) -> None:
        self._fail_next_send = on

    def hold_pending(self, on: bool = True) -> None:
        """When set, mined blocks do NOT include queued coordinator txs (stuck tx)."""
        self._hold_pending = on

    def force_revert(self, kind: str, on: bool = True) -> None:
        """Force a tx kind (settle_batch|deposit_settlement|debit) to revert when mined."""
        self._revert_kinds.add(kind) if on else self._revert_kinds.discard(kind)

    # external (non-coordinator) actions that emit watched events on the next mine ──────
    def external_deposit(self, developer: str, amount: int) -> str:
        dev = developer.lower()

        def apply(num: int, bh: str) -> tuple[int, list[LogSpec]]:
            self._escrow_bal[dev] += amount
            return 1, [("Deposited", self.escrow_address, {"developer": dev, "amount": amount})]

        return self._enqueue("external", apply)

    def external_withdraw(self, developer: str, amount: int) -> str:
        dev = developer.lower()

        def apply(num: int, bh: str) -> tuple[int, list[LogSpec]]:
            if self._escrow_bal[dev] < amount:
                return 0, []
            self._escrow_bal[dev] -= amount
            return 1, [("Withdrawn", self.escrow_address, {"developer": dev, "amount": amount})]

        return self._enqueue("external", apply)

    def external_slash(self, provider: str, amount: int, evidence_hash: str) -> str:
        prov = provider.lower()

        def apply(num: int, bh: str) -> tuple[int, list[LogSpec]]:
            return 1, [
                (
                    "Slashed",
                    self.staking_address,
                    {"provider": prov, "amount": amount, "evidenceHash": evidence_hash},
                )
            ]

        return self._enqueue("external", apply)

    def _enqueue(self, kind: str, apply: Apply, nonce: int | None = None) -> str:
        tx_hash = self._txhash()
        self._queue.append((kind, tx_hash, nonce, apply))
        return tx_hash

    # ── mining / reorg ────────────────────────────────────────────────────────────────
    def mine(self, n: int = 1) -> None:
        for _ in range(n):
            number = len(self._blocks)
            parent = self._blocks[-1]
            bh = self._bhash(number)
            # Externals mine FIFO; coordinator txs mine strictly in nonce order (a tx at nonce
            # k+1 cannot be included before k) — so a failed low-nonce send stalls higher ones,
            # exactly as Ethereum does. Held txs stay pending.
            externals = [it for it in self._queue if it[0] == "external"]
            txs = {it[2]: it for it in self._queue if it[0] == "tx" and not self._hold_pending}
            held = [it for it in self._queue if it[0] == "tx" and self._hold_pending]
            included = list(externals)
            while self._mined_nonce in txs:
                included.append(txs.pop(self._mined_nonce))
                self._mined_nonce += 1
            self._queue = held + list(txs.values())  # gap-blocked txs wait for their turn

            block_logs: list[ChainLog] = []
            for kind, tx_hash, _nonce, apply in included:
                status, specs = apply(number, bh)
                if kind == "tx":
                    self._receipts[tx_hash] = Receipt(tx_hash, status, number, bh)
                for name, address, args in specs:
                    block_logs.append(
                        ChainLog(name, address, tx_hash, len(block_logs), number, bh, args)
                    )
            self._logs[number] = block_logs
            self._blocks.append(BlockRef(number, bh, parent.hash))

    def reorg(self, depth: int = 1, remine: int = 1) -> None:
        """Orphan the top ``depth`` blocks and mine ``remine`` fresh ones with new hashes.

        Events that lived only on the orphaned blocks disappear; anything the watcher applied
        from them must be rolled back. Receipts on orphaned blocks are cleared."""
        for _ in range(depth):
            if len(self._blocks) <= 1:
                break
            gone = self._blocks.pop()
            for log in self._logs.pop(gone.number, []):
                self._receipts.pop(log.tx_hash, None)
        self._salt += 1
        self.mine(remine)

    # ── ChainClient reads ──────────────────────────────────────────────────────────────
    @property
    def coordinator_address(self) -> str:
        return self._coord

    async def escrow_balance_of(self, address: str) -> int:
        return self._escrow_bal[address.lower()]

    async def staking_earnings_of(self, address: str) -> int:
        return self._earnings[address.lower()]

    async def settlement_pool(self) -> int:
        return self._pool

    async def latest_block(self) -> int:
        return len(self._blocks) - 1

    async def get_block(self, number: int) -> BlockRef:
        if number >= len(self._blocks):
            raise ChainError(f"block {number} not found")
        return self._blocks[number]

    async def get_logs(self, from_block: int, to_block: int) -> list[ChainLog]:
        out: list[ChainLog] = []
        for num in range(max(0, from_block), min(to_block, len(self._blocks) - 1) + 1):
            out.extend(self._logs.get(num, []))
        out.sort(key=lambda log: (log.block_number, log.log_index))
        return out

    async def get_receipt(self, tx_hash: str) -> Receipt | None:
        return self._receipts.get(tx_hash)

    async def get_nonce(self, *, pending: bool = True) -> int:
        return self._mined_nonce

    # ── ChainClient writes ──────────────────────────────────────────────────────────────
    def _broadcast(
        self, kind: str, nonce: int, effect: Callable[[], tuple[int, list[LogSpec]]]
    ) -> str:
        if self._fail_next_send:
            self._fail_next_send = False
            raise ChainError("simulated broadcast failure")

        def apply(num: int, bh: str) -> tuple[int, list[LogSpec]]:
            if kind in self._revert_kinds:
                return 0, []
            return effect()

        return self._enqueue("tx", apply, nonce)

    async def send_settle_batch(self, providers: list[str], amounts: list[int], nonce: int) -> str:
        def effect() -> tuple[int, list[LogSpec]]:
            total = sum(amounts)
            if total > self._pool:
                return 0, []  # pool underfunded → revert (mirrors the contract)
            self._pool -= total
            logs: list[LogSpec] = []
            for p, a in zip(providers, amounts, strict=True):
                self._earnings[p.lower()] += a
                logs.append(("Settled", self.staking_address, {"provider": p.lower(), "amount": a}))
            return 1, logs

        return self._broadcast("settle_batch", nonce, effect)

    async def send_deposit_settlement(self, amount: int, nonce: int) -> str:
        def effect() -> tuple[int, list[LogSpec]]:
            self._pool += amount
            return 1, []

        return self._broadcast("deposit_settlement", nonce, effect)

    async def send_debit(self, developer: str, amount: int, nonce: int) -> str:
        dev = developer.lower()

        def effect() -> tuple[int, list[LogSpec]]:
            if self._escrow_bal[dev] < amount:
                return 0, []
            self._escrow_bal[dev] -= amount
            return 1, [
                (
                    "Debited",
                    self.escrow_address,
                    {"developer": dev, "amount": amount, "to": _TREASURY},
                )
            ]

        return self._broadcast("debit", nonce, effect)
