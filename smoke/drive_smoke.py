"""Drive the P0 end-to-end smoke test against a running control plane.

Automates runbook P0.3 (happy path) + the ledger assertions of P0.1–P0.5:

    register developer + provider → declare caps → seed stake → upload input →
    submit job → wait for the agent to run it → verify result + ledger.

Run from the repo root, with the stack already up (``docker compose up --build``) and the
smoke image built (``docker build -f smoke/Dockerfile --build-arg SCRIPT=run.py -t
gridix-smoke .``). The script registers the provider and prints the exact command to start
the agent, then waits for you to start it before submitting work.

    python smoke/drive_smoke.py                 # happy path, image gridix-smoke
    python smoke/drive_smoke.py --egress        # egress-isolation probe (expects BLOCKED)
    python smoke/drive_smoke.py --timeout        # timeout kill (expects failed/timeout)

Env:
    GRIDIX_API_URL   default http://localhost:8000
    GRIDIX_COMPOSE   compose command, default "docker compose"
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import httpx

API_URL = os.environ.get("GRIDIX_API_URL", "http://localhost:8000").rstrip("/")
COMPOSE = os.environ.get("GRIDIX_COMPOSE", "docker compose")
REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_SCRIPT = REPO_ROOT / "smoke" / "seed_stake.py"

TERMINAL = {"completed", "failed", "timeout"}


def _hr(title: str) -> None:
    print(f"\n=== {title} ===")


def _seed_stake(provider_id: str, amount: str = "200") -> None:
    """Fund provider stake by piping seed_stake.py into the api container."""
    cmd = [
        *shlex.split(COMPOSE),
        "exec",
        "-T",
        "-e",
        f"SEED_PROVIDER_ID={provider_id}",
        "-e",
        f"SEED_AMOUNT={amount}",
        "api",
        "python",
    ]
    with SEED_SCRIPT.open("rb") as stdin:
        result = subprocess.run(cmd, stdin=stdin, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout, result.stderr, sep="\n", file=sys.stderr)
        raise SystemExit(f"stake seeding failed (exit {result.returncode}) — is the stack up?")
    print(result.stdout.strip())


async def _register(client: httpx.AsyncClient, role: str, name: str) -> tuple[str, str]:
    resp = await client.post(f"/{role}s", json={"name": name})
    resp.raise_for_status()
    body = resp.json()
    return body["id"], body["api_key"]


async def _wait_for_terminal(
    client: httpx.AsyncClient, dev_key: str, job_id: str, budget_s: float
) -> dict:
    headers = {"Authorization": f"Bearer {dev_key}"}
    deadline = time.monotonic() + budget_s
    last = ""
    while time.monotonic() < deadline:
        resp = await client.get(f"/jobs/{job_id}", headers=headers)
        resp.raise_for_status()
        job = resp.json()
        if job["status"] != last:
            print(f"  job {job_id[:8]} → {job['status']}")
            last = job["status"]
        if job["status"] in TERMINAL:
            return job
        await asyncio.sleep(1.0)
    raise SystemExit(f"job did not reach a terminal state within {budget_s:.0f}s (stuck in {last})")


async def main() -> int:
    parser = argparse.ArgumentParser(description="GRIDIX P0 end-to-end smoke driver")
    parser.add_argument("--egress", action="store_true", help="egress-isolation probe")
    parser.add_argument("--timeout", action="store_true", help="timeout-kill probe")
    args = parser.parse_args()

    if args.egress:
        image, expect, budget, tmo = "gridix-smoke-netprobe", "BLOCKED", 120, 60
    elif args.timeout:
        image, expect, budget, tmo = "gridix-smoke-sleeper", None, 90, 5
    else:
        image, expect, budget, tmo = "gridix-smoke", None, 120, 120

    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        _hr("health")
        health = await client.get("/health")
        print(f"  /health → {health.status_code} {health.text[:120]}")
        health.raise_for_status()

        _hr("register")
        dev_id, dev_key = await _register(client, "developer", "smoke-dev")
        prov_id, prov_key = await _register(client, "provider", "smoke-prov")
        print(f"  developer {dev_id}\n  provider  {prov_id}")
        r = await client.patch(
            "/providers/me",
            headers={"Authorization": f"Bearer {prov_key}"},
            json={"cpu_cores": 8, "memory_mb": 16000, "max_concurrent": 4},
        )
        r.raise_for_status()

        _hr("seed stake")
        _seed_stake(prov_id)

        _hr("upload input")
        payload = b"gridix-smoke-input"
        expected_output = hashlib.sha256(payload).hexdigest()
        up = await client.post(
            "/blobs",
            headers={"Authorization": f"Bearer {dev_key}"},
            files={"file": ("input", payload, "application/octet-stream")},
        )
        up.raise_for_status()
        input_ref = up.json()["ref"]
        print(f"  input_ref {input_ref}")

        _hr("start the agent, then press Enter")
        print("  In another terminal on this host, run:\n")
        print("    cd agent && pip install -r requirements.txt")
        print(f"    GRIDIX_API_URL={API_URL} GRIDIX_PROVIDER_KEY={prov_key} python agent.py\n")
        input("  Press Enter once the agent logs 'agent started' ... ")

        _hr("submit job")
        job_req = {
            "image_ref": image,
            "input_ref": input_ref,
            "resource_spec": {"cpu_cores": 1, "memory_mb": 256},
            "timeout_seconds": tmo,
        }
        sub = await client.post(
            "/jobs", headers={"Authorization": f"Bearer {dev_key}"}, json=job_req
        )
        sub.raise_for_status()
        job_id = sub.json()["id"]
        print(f"  submitted job {job_id} (image={image}, timeout={tmo}s)")

        _hr("wait for terminal state")
        job = await _wait_for_terminal(client, dev_key, job_id, budget)

        _hr("verify")
        ok = True
        if args.timeout:
            ok = job["status"] in {"failed", "timeout"}
            print(f"  status {job['status']} — expected failed/timeout: {'PASS' if ok else 'FAIL'}")
            print("  now check the host: `docker ps -a` should show NO leftover gridix-* container")
        else:
            ok = job["status"] == "completed"
            print(f"  status {job['status']} — expected completed: {'PASS' if ok else 'FAIL'}")
            if ok:
                res = await client.get(
                    f"/jobs/{job_id}/result", headers={"Authorization": f"Bearer {dev_key}"}
                )
                res.raise_for_status()
                got = res.text
                if expect is not None:
                    match = got.strip() == expect
                    print(f"  result {got!r} — expected {expect!r}: {'PASS' if match else 'FAIL'}")
                    ok = ok and match
                else:
                    match = got.strip() == expected_output
                    print(f"  result sha256 matches input: {'PASS' if match else 'FAIL'}")
                    ok = ok and match

        _hr("ledger (audit trail)")
        audit = await client.get(
            f"/jobs/{job_id}/audit", headers={"Authorization": f"Bearer {dev_key}"}
        )
        audit.raise_for_status()
        a = audit.json()
        print(f"  attempts: {len(a['attempts'])}, ledger entries: {len(a['ledger'])}")
        debit = sum(float(e["amount"]) for e in a["ledger"] if e["direction"] == "debit")
        credit = sum(float(e["amount"]) for e in a["ledger"] if e["direction"] == "credit")
        balanced = abs(debit - credit) < 1e-6
        state = "BALANCED" if balanced else "IMBALANCED"
        print(f"  double-entry: debit={debit} credit={credit} — {state}")
        for e in a["ledger"]:
            reason = e.get("reason", "")
            print(f"    {e['direction']:<6} {e['account']:<10} {e['amount']:>10}  {reason}")
        ok = ok and balanced

    print(f"\n{'✅ SMOKE PASS' if ok else '❌ SMOKE FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
