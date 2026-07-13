"""The ChainClient seam — every chain interaction goes through this interface.

Two implementations exist: :class:`~app.chain.fake.FakeChain` (in-memory, drives the whole
hermetic test suite and local dev) and :class:`Web3ChainClient` (real JSON-RPC, used only
against a live network). Callers depend on the ABC, never on web3, so nothing but the real
client ever imports it.

Design notes:
* Amounts are **raw token units** (USDC has 6 decimals) as ``int`` — no floats near money.
* Outbound txs take an explicit ``nonce`` chosen by the settlement engine (which persists it
  before broadcast), so a crash-and-recover replaces a stuck tx at the same nonce instead of
  ever sending a second payout.
* Reads (``balance_of``, ``earnings_of``) are cheap and cacheable by the caller.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# ── value objects returned by the client ───────────────────────────────────────────────


@dataclass(frozen=True)
class BlockRef:
    """A block's identity — enough to detect a reorg (same number, different hash)."""

    number: int
    hash: str
    parent_hash: str


@dataclass(frozen=True)
class Receipt:
    """A mined transaction's outcome. ``status`` is 1 for success, 0 for a revert."""

    tx_hash: str
    status: int
    block_number: int
    block_hash: str


@dataclass(frozen=True)
class ChainLog:
    """A decoded event log from one of our contracts.

    ``args`` holds the decoded, JSON-safe event fields (addresses lowercased, ints as ``int``).
    """

    event_name: str  # Deposited | Withdrawn | Debited | Settled | Slashed
    address: str  # emitting contract, lowercased
    tx_hash: str
    log_index: int
    block_number: int
    block_hash: str
    args: dict


class ChainError(Exception):
    """A recoverable chain-interaction error (RPC down, tx dropped). Never crashes a loop."""


class ChainClient(ABC):
    """Everything the settlement engine, watcher, and payment provider need from a chain."""

    @property
    @abstractmethod
    def coordinator_address(self) -> str:
        """The lowercased EOA that signs debit/settleBatch/depositSettlement."""

    # ── reads ──────────────────────────────────────────────────────────────────────────

    @abstractmethod
    async def escrow_balance_of(self, address: str) -> int:
        """GridixEscrow.balanceOf(developer) in raw units."""

    @abstractmethod
    async def staking_earnings_of(self, address: str) -> int:
        """GridixStaking.earningsOf(provider) — settled-but-unwithdrawn, in raw units."""

    @abstractmethod
    async def settlement_pool(self) -> int:
        """GridixStaking.settlementPool() — USDC available to pay out, in raw units."""

    @abstractmethod
    async def latest_block(self) -> int:
        """Height of the latest block."""

    @abstractmethod
    async def get_block(self, number: int) -> BlockRef:
        """Identity of block ``number`` (for reorg detection)."""

    @abstractmethod
    async def get_logs(self, from_block: int, to_block: int) -> list[ChainLog]:
        """Decoded Deposited/Withdrawn/Debited/Settled/Slashed logs in [from, to] inclusive."""

    @abstractmethod
    async def get_receipt(self, tx_hash: str) -> Receipt | None:
        """Receipt for a broadcast tx, or ``None`` if not yet mined."""

    @abstractmethod
    async def get_nonce(self, *, pending: bool = True) -> int:
        """Transaction count for the coordinator account (pending or latest)."""

    # ── writes (all COORDINATOR_ROLE) ───────────────────────────────────────────────────

    @abstractmethod
    async def send_settle_batch(self, providers: list[str], amounts: list[int], nonce: int) -> str:
        """GridixStaking.settleBatch — credit N providers in one tx. Returns the tx hash."""

    @abstractmethod
    async def send_deposit_settlement(self, amount: int, nonce: int) -> str:
        """GridixStaking.depositSettlement — fund the payout pool. Returns the tx hash."""

    @abstractmethod
    async def send_debit(self, developer: str, amount: int, nonce: int) -> str:
        """GridixEscrow.debit — pull consumed developer escrow to treasury. Returns tx hash."""


# ── minimal ABIs (only the fragments we call/decode) ───────────────────────────────────

_ESCROW_ABI = [
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "developer", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "debit",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "developer", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "event",
        "name": "Deposited",
        "anonymous": False,
        "inputs": [
            {"name": "developer", "type": "address", "indexed": True},
            {"name": "amount", "type": "uint256", "indexed": False},
        ],
    },
    {
        "type": "event",
        "name": "Withdrawn",
        "anonymous": False,
        "inputs": [
            {"name": "developer", "type": "address", "indexed": True},
            {"name": "amount", "type": "uint256", "indexed": False},
        ],
    },
    {
        "type": "event",
        "name": "Debited",
        "anonymous": False,
        "inputs": [
            {"name": "developer", "type": "address", "indexed": True},
            {"name": "amount", "type": "uint256", "indexed": False},
            {"name": "to", "type": "address", "indexed": True},
        ],
    },
]

_STAKING_ABI = [
    {
        "type": "function",
        "name": "earningsOf",
        "stateMutability": "view",
        "inputs": [{"name": "provider", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "settlementPool",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "settleBatch",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "providers", "type": "address[]"},
            {"name": "amounts", "type": "uint256[]"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "depositSettlement",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "amount", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "event",
        "name": "Settled",
        "anonymous": False,
        "inputs": [
            {"name": "provider", "type": "address", "indexed": True},
            {"name": "amount", "type": "uint256", "indexed": False},
        ],
    },
    {
        "type": "event",
        "name": "Slashed",
        "anonymous": False,
        "inputs": [
            {"name": "provider", "type": "address", "indexed": True},
            {"name": "amount", "type": "uint256", "indexed": False},
            {"name": "evidenceHash", "type": "bytes32", "indexed": True},
        ],
    },
]

_ERC20_APPROVE_ABI = [
    {
        "type": "function",
        "name": "approve",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
]

_WATCHED_EVENTS = {"Deposited", "Withdrawn", "Debited", "Settled", "Slashed"}


class Web3ChainClient(ChainClient):
    """Real JSON-RPC client. Lazily imports web3/eth-account so tests never pull them in.

    Requires the ``chain`` optional dependency: ``pip install '.[chain]'``.
    """

    def __init__(
        self,
        *,
        rpc_url: str,
        chain_id: int,
        escrow_address: str,
        staking_address: str,
        coordinator_private_key: str,
        gas_multiplier: float = 1.25,
        log_window: int = 500,
    ) -> None:
        try:
            from eth_account import Account
            from web3 import AsyncWeb3

            # AsyncHTTPProvider moved across web3 6/7 — accept either location.
            try:
                from web3 import AsyncHTTPProvider
            except ImportError:  # web3 < 7
                from web3.providers.async_rpc import AsyncHTTPProvider
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without extra
            raise ChainError(
                "web3 is required for on-chain settlement; install with '.[chain]'"
            ) from exc

        self._w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url))
        self._chain_id = chain_id
        self._acct = Account.from_key(coordinator_private_key)
        self._escrow = self._w3.eth.contract(
            address=self._w3.to_checksum_address(escrow_address), abi=_ESCROW_ABI
        )
        self._staking = self._w3.eth.contract(
            address=self._w3.to_checksum_address(staking_address), abi=_STAKING_ABI
        )
        self._gas_multiplier = gas_multiplier
        self._log_window = max(1, log_window)
        self._addr_lc = self._acct.address.lower()

    @property
    def coordinator_address(self) -> str:
        return self._addr_lc

    async def escrow_balance_of(self, address: str) -> int:
        cs = self._w3.to_checksum_address(address)
        return int(await self._escrow.functions.balanceOf(cs).call())

    async def staking_earnings_of(self, address: str) -> int:
        cs = self._w3.to_checksum_address(address)
        return int(await self._staking.functions.earningsOf(cs).call())

    async def settlement_pool(self) -> int:
        return int(await self._staking.functions.settlementPool().call())

    async def latest_block(self) -> int:
        return int(await self._w3.eth.block_number)

    async def get_block(self, number: int) -> BlockRef:
        b = await self._w3.eth.get_block(number)
        return BlockRef(
            number=int(b["number"]),
            hash=b["hash"].hex() if hasattr(b["hash"], "hex") else str(b["hash"]),
            parent_hash=(
                b["parentHash"].hex() if hasattr(b["parentHash"], "hex") else str(b["parentHash"])
            ),
        )

    async def get_logs(self, from_block: int, to_block: int) -> list[ChainLog]:
        logs: list[ChainLog] = []
        # Scan in bounded windows: public RPCs reject wide eth_getLogs ranges, so a catch-up
        # after downtime (or a fresh cursor) must never ask for genesis-to-now in one call.
        start = from_block
        while start <= to_block:
            end = min(start + self._log_window - 1, to_block)
            for contract in (self._escrow, self._staking):
                for name in _events_of(contract):
                    event = contract.events[name]()
                    try:
                        raw = await self._w3.eth.get_logs(
                            {
                                "address": contract.address,
                                "fromBlock": start,
                                "toBlock": end,
                                "topics": [event.topic],
                            }
                        )
                    except Exception as exc:  # noqa: BLE001 - surface as a recoverable ChainError
                        raise ChainError(f"get_logs {start}-{end} failed: {exc}") from exc
                    for entry in raw:
                        decoded = event.process_log(entry)
                        logs.append(_to_chain_log(name, contract.address.lower(), decoded))
            start = end + 1
        logs.sort(key=lambda log: (log.block_number, log.log_index))
        return logs

    async def get_receipt(self, tx_hash: str) -> Receipt | None:
        try:
            r = await self._w3.eth.get_transaction_receipt(tx_hash)
        except Exception:  # noqa: BLE001 - not-yet-mined raises; treat as pending
            return None
        if r is None:
            return None
        return Receipt(
            tx_hash=tx_hash,
            status=int(r["status"]),
            block_number=int(r["blockNumber"]),
            block_hash=(
                r["blockHash"].hex() if hasattr(r["blockHash"], "hex") else str(r["blockHash"])
            ),
        )

    async def get_nonce(self, *, pending: bool = True) -> int:
        block = "pending" if pending else "latest"
        return int(await self._w3.eth.get_transaction_count(self._acct.address, block))

    async def _send(self, fn, nonce: int) -> str:
        base = {
            "from": self._acct.address,
            "nonce": nonce,
            "chainId": self._chain_id,
        }
        gas = await fn.estimate_gas({"from": self._acct.address})
        base["gas"] = int(gas * self._gas_multiplier)
        base["maxFeePerGas"] = await self._w3.eth.gas_price
        base["maxPriorityFeePerGas"] = self._w3.to_wei(1, "gwei")
        tx = await fn.build_transaction(base)
        signed = self._acct.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h = await self._w3.eth.send_raw_transaction(raw)
        return h.hex() if hasattr(h, "hex") else str(h)

    async def send_settle_batch(self, providers: list[str], amounts: list[int], nonce: int) -> str:
        cs = [self._w3.to_checksum_address(p) for p in providers]
        return await self._send(self._staking.functions.settleBatch(cs, amounts), nonce)

    async def send_deposit_settlement(self, amount: int, nonce: int) -> str:
        return await self._send(self._staking.functions.depositSettlement(amount), nonce)

    async def send_debit(self, developer: str, amount: int, nonce: int) -> str:
        cs = self._w3.to_checksum_address(developer)
        return await self._send(self._escrow.functions.debit(cs, amount), nonce)


def _events_of(contract) -> list[str]:
    return [e.event_name for e in contract.events if e.event_name in _WATCHED_EVENTS]


def _to_chain_log(name: str, address: str, decoded) -> ChainLog:
    args = {}
    for k, v in decoded["args"].items():
        if isinstance(v, bytes):
            args[k] = "0x" + v.hex()
        elif isinstance(v, str) and v.startswith("0x") and len(v) == 42:
            args[k] = v.lower()
        else:
            args[k] = int(v) if isinstance(v, int) else v
    txh = decoded["transactionHash"]
    bh = decoded["blockHash"]
    return ChainLog(
        event_name=name,
        address=address,
        tx_hash=txh.hex() if hasattr(txh, "hex") else str(txh),
        log_index=int(decoded["logIndex"]),
        block_number=int(decoded["blockNumber"]),
        block_hash=bh.hex() if hasattr(bh, "hex") else str(bh),
        args=args,
    )
