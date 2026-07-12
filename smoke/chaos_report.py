"""Load/chaos report + invariant gate. Run against the live coordinator DB (via the api
container). Scopes to the load test's developer (CHAOS_DEV_ID). Prints throughput/latency and
asserts the two DR invariants; exits non-zero if either fails."""

import asyncio
import os
import sys

from app.db import get_sessionmaker
from app.ledger import verify_ledger_integrity
from sqlalchemy import text

DEV = os.environ["CHAOS_DEV_ID"]


async def main() -> int:
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(
                text("SELECT status, count(*) FROM jobs WHERE developer_id=:d GROUP BY status"),
                {"d": DEV},
            )
        ).all()
        status = {str(r[0]): r[1] for r in rows}
        total = sum(status.values())
        terminal = sum(status.get(k, 0) for k in ("completed", "failed", "timeout"))
        nonterminal = total - terminal

        m = (
            await s.execute(
                text(
                    "SELECT count(*) FILTER (WHERE status='completed'), "
                    "extract(epoch FROM (max(updated_at)-min(created_at))), "
                    "avg(extract(epoch FROM (updated_at-created_at))), "
                    "max(extract(epoch FROM (updated_at-created_at))) "
                    "FROM jobs WHERE developer_id=:d"
                ),
                {"d": DEV},
            )
        ).one()
        completed, span, lat_avg, lat_max = (float(x) if x is not None else 0.0 for x in m)

        disc = await verify_ledger_integrity(s)
        deb = float(
            await s.scalar(
                text("SELECT coalesce(sum(amount),0) FROM ledger_entries WHERE direction='debit'")
            )
        )
        cred = float(
            await s.scalar(
                text("SELECT coalesce(sum(amount),0) FROM ledger_entries WHERE direction='credit'")
            )
        )
        orphans = int(
            await s.scalar(
                text(
                    "SELECT count(*) FROM job_attempts a "
                    "LEFT JOIN jobs j ON a.job_id=j.id WHERE j.id IS NULL"
                )
            )
        )

    tput = completed / span if span > 0 else 0.0
    print(f"jobs: {total}  status={status}")
    print(f"throughput: {tput:.2f} completed-jobs/s over {span:.1f}s")
    print(f"latency: avg {lat_avg:.1f}s  max {lat_max:.1f}s")
    print(f"ledger: debit={deb:.8f} credit={cred:.8f} discrepancies={len(disc)} orphans={orphans}")

    inv1 = (not disc) and abs(deb - cred) < 1e-6 and orphans == 0
    inv2 = nonterminal == 0
    print(f"INVARIANT 1 (ledger correctness): {'PASS' if inv1 else 'FAIL'}")
    v2 = "PASS" if inv2 else "FAIL"
    print(f"INVARIANT 2 (no job silently lost): {v2} (non-terminal={nonterminal})")
    return 0 if (inv1 and inv2) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
