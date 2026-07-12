"""Post-restore integrity gate for the DR drill.

Run against a freshly restored database (point GRIDIX_DATABASE_URL at it). Asserts the
invariants that make a restore trustworthy, and prints counts for baseline comparison:
  1. Ledger balances — every double-entry group has debits == credits, and total debit ==
     total credit (money is intact).
  2. No orphan records — no attempt/ledger row points at a missing job, no job at a missing
     developer, and no terminal job with zero attempts (referential integrity survived).
Exits non-zero if any check fails, so restore.sh + this script form a pass/fail DR test.
"""

import asyncio
import sys

from app.db import get_sessionmaker
from app.ledger import verify_ledger_integrity
from sqlalchemy import text

_ORPHAN_QUERIES = {
    "attempts_without_job": (
        "SELECT count(*) FROM job_attempts a LEFT JOIN jobs j ON a.job_id = j.id WHERE j.id IS NULL"
    ),
    "jobs_without_developer": (
        "SELECT count(*) FROM jobs j "
        "LEFT JOIN developers d ON j.developer_id = d.id WHERE d.id IS NULL"
    ),
    "ledger_without_job": (
        "SELECT count(*) FROM ledger_entries e "
        "LEFT JOIN jobs j ON e.job_id = j.id WHERE e.job_id IS NOT NULL AND j.id IS NULL"
    ),
    "terminal_jobs_without_attempt": (
        "SELECT count(*) FROM jobs j "
        "LEFT JOIN job_attempts a ON a.job_id = j.id "
        "WHERE j.status IN ('completed','failed','timeout') AND a.id IS NULL"
    ),
}


async def main() -> int:
    async with get_sessionmaker()() as session:
        discrepancies = await verify_ledger_integrity(session)
        orphans = {
            name: (await session.scalar(text(sql))) or 0 for name, sql in _ORPHAN_QUERIES.items()
        }
        debit = float(
            await session.scalar(
                text("SELECT coalesce(sum(amount),0) FROM ledger_entries WHERE direction='debit'")
            )
        )
        credit = float(
            await session.scalar(
                text("SELECT coalesce(sum(amount),0) FROM ledger_entries WHERE direction='credit'")
            )
        )
        counts = {
            "jobs": await session.scalar(text("SELECT count(*) FROM jobs")),
            "providers": await session.scalar(text("SELECT count(*) FROM providers")),
            "ledger_entries": await session.scalar(text("SELECT count(*) FROM ledger_entries")),
            "reputation_events": await session.scalar(
                text("SELECT count(*) FROM reputation_events")
            ),
        }
        by_status = list(
            await session.execute(
                text("SELECT status, count(*) FROM jobs GROUP BY status ORDER BY status")
            )
        )

    print("counts:", counts)
    print("jobs by status:", {str(s): c for s, c in by_status})
    print(f"ledger: debit={debit:.8f} credit={credit:.8f} discrepancies={len(discrepancies)}")
    for name, count in orphans.items():
        print(f"orphans[{name}]: {count}")

    ok = not discrepancies and abs(debit - credit) < 1e-6 and all(c == 0 for c in orphans.values())
    print("RESTORE VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
