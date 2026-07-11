"""Tamper-evident audit log (Session 12.6).

An append-only, hash-chained log of security-relevant events. Each entry commits to the
previous entry's hash, so altering or deleting any record breaks the chain — detectable by
:func:`verify_audit_chain`. This is the retained, tamper-evident audit trail; other tables
(job_attempts, ledger_entries, reputation_events, disputes) are the domain-specific trails
this ties together.
"""

import hashlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.fraud_proof import canonical_evidence
from app.models import AuditLogEntry

_GENESIS = "0" * 64


def _entry_hash(seq: int, event: str, data: dict, prev_hash: str) -> str:
    payload = {"seq": seq, "event": event, "data": data, "prev_hash": prev_hash}
    return hashlib.sha256(canonical_evidence(payload)).hexdigest()


async def append_audit(session: AsyncSession, event: str, data: dict) -> AuditLogEntry:
    """Append an event to the hash chain and return the new entry."""
    last = await session.scalar(select(AuditLogEntry).order_by(AuditLogEntry.seq.desc()).limit(1))
    seq = (last.seq + 1) if last else 1
    prev_hash = last.entry_hash if last else _GENESIS
    entry = AuditLogEntry(
        seq=seq,
        event=event,
        data=data,
        prev_hash=prev_hash,
        entry_hash=_entry_hash(seq, event, data, prev_hash),
    )
    session.add(entry)
    await session.flush()
    return entry


async def verify_audit_chain(session: AsyncSession) -> bool:
    """Recompute the chain and return whether it is intact (no tampering/deletion)."""
    entries = list(await session.scalars(select(AuditLogEntry).order_by(AuditLogEntry.seq.asc())))
    prev = _GENESIS
    expected_seq = 1
    for e in entries:
        if e.seq != expected_seq or e.prev_hash != prev:
            return False
        if _entry_hash(e.seq, e.event, e.data, e.prev_hash) != e.entry_hash:
            return False
        prev = e.entry_hash
        expected_seq += 1
    return True


async def audit_count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(AuditLogEntry)) or 0)
