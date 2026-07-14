"""GPU benchmark harness — the provider-agent side of the anti-fraud story.

The coordinator's `app.benchmark.validate_benchmark` can only be as honest as the numbers it
scores. This module MEASURES those numbers on the provider's own box instead of trusting a
self-declared claim:

* **identity + VRAM** via ``nvidia-smi`` — the ground truth for what card is actually present;
* **throughput (TFLOPs)** via a containerized GEMM run under the same ``--gpus`` passthrough as
  real jobs — so a throttled or virtualized card can't pass as a full one;
* **hardware fingerprint** from the GPU UUID(s) — the same physical card reused as "many nodes"
  produces the same fingerprint, which the coordinator rejects as a collision.

The measured metrics are HMAC-signed with the provider key (byte-for-byte the same canonical
encoding as `app.fraud_proof.canonical_evidence`, so the coordinator's `verify_signature`
accepts them) and POSTed to ``/agent/benchmark``. Runs once at onboarding.

Standalone (stdlib + httpx only) so the agent stays dependency-light; no import of ``app``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
from typing import Any

# GPU families the coordinator scores — MUST match app.benchmark.GPU_REFERENCE_TFLOPS keys.
# Ordered most-specific first so "A100" wins before a bare vendor substring.
_KNOWN_FAMILIES = ("H100", "A100", "V100", "T4", "L4")


def canonical_evidence(evidence: dict[str, Any]) -> bytes:
    """Deterministic byte encoding — identical to app.fraud_proof.canonical_evidence."""
    return json.dumps(
        evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode()


def sign_metrics(metrics: dict, provider_key: str) -> str:
    """HMAC-SHA256 over the canonical metrics — matches app.benchmark.sign_report (64 hex)."""
    return hmac.new(provider_key.encode(), canonical_evidence(metrics), hashlib.sha256).hexdigest()


def _run(argv: list[str], timeout: float) -> str | None:
    """Run a command, returning stdout, or None on any failure (missing binary, error, timeout)."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=True)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return None


def normalize_gpu_model(name: str) -> str | None:
    """Map an nvidia-smi product name ('NVIDIA A100-SXM4-40GB') to a scored family ('A100')."""
    upper = name.upper()
    for family in _KNOWN_FAMILIES:
        if family in upper:
            return family
    return None


def probe_nvidia_smi(timeout: float = 10.0) -> list[dict]:
    """Return one dict per GPU: {name, vram_mb, uuid}. Empty list if no NVIDIA GPU / driver."""
    out = _run(
        ["nvidia-smi", "--query-gpu=name,memory.total,uuid", "--format=csv,noheader,nounits"],
        timeout,
    )
    if not out:
        return []
    gpus: list[dict] = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            vram_mb = int(float(parts[1]))
        except ValueError:
            continue
        gpus.append({"name": parts[0], "vram_mb": vram_mb, "uuid": parts[2]})
    return gpus


def measure_tflops(bench_image: str | None, timeout: float = 120.0) -> float:
    """Run a containerized GEMM benchmark and parse achieved TFLOPs; 0.0 if unavailable.

    The image runs under `--gpus all` (same passthrough as real jobs) and must print a line
    ``GRIDIX_TFLOPS=<float>``. Left image-agnostic so any CUDA GEMM harness works.
    """
    if not bench_image:
        return 0.0
    out = _run(["docker", "run", "--rm", "--gpus", "all", bench_image], timeout)
    if not out:
        return 0.0
    for line in out.splitlines():
        if line.startswith("GRIDIX_TFLOPS="):
            try:
                return float(line.split("=", 1)[1].strip())
            except ValueError:
                return 0.0
    return 0.0


def hardware_fingerprint(gpus: list[dict]) -> str | None:
    """Stable per physical GPU set (sorted GPU UUIDs). The same card reused as several 'nodes'
    yields the same fingerprint, which the coordinator flags as a collision."""
    uuids = sorted(g["uuid"] for g in gpus if g.get("uuid"))
    if not uuids:
        return None
    return hashlib.sha256("|".join(uuids).encode()).hexdigest()


def collect_metrics(
    *,
    cpu_cores: int,
    memory_mb: int,
    bench_image: str | None = None,
    nvidia_timeout: float = 10.0,
    bench_timeout: float = 120.0,
) -> dict:
    """Assemble MEASURED benchmark metrics — never self-declared hardware."""
    gpus = probe_nvidia_smi(nvidia_timeout)
    metrics: dict[str, Any] = {
        "cpu_cores": cpu_cores,
        "memory_mb": memory_mb,
        "gpu_count": len(gpus),
    }
    if gpus:
        metrics["gpu_model"] = normalize_gpu_model(gpus[0]["name"])
        metrics["gpu_name_raw"] = gpus[0]["name"]
        metrics["gpu_vram_mb"] = min(g["vram_mb"] for g in gpus)  # the weakest card bounds a job
        metrics["gpu_tflops"] = measure_tflops(bench_image, bench_timeout)
        fingerprint = hardware_fingerprint(gpus)
        if fingerprint:
            metrics["hardware_fingerprint"] = fingerprint
    else:
        metrics["gpu_model"] = None
        metrics["gpu_vram_mb"] = 0
        metrics["gpu_tflops"] = 0.0
    return metrics


async def submit_benchmark(http_client, base_url: str, provider_key: str, metrics: dict) -> dict:
    """Sign the measured metrics and POST them to the coordinator; return the stored report."""
    signature = sign_metrics(metrics, provider_key)
    resp = await http_client.post(
        f"{base_url.rstrip('/')}/agent/benchmark",
        json={"metrics": metrics, "signature": signature},
    )
    resp.raise_for_status()
    return resp.json()


async def _main() -> None:  # pragma: no cover - operational entrypoint, exercised on a real box
    import httpx

    base_url = os.environ["GRIDIX_COORDINATOR_URL"]
    provider_key = os.environ["GRIDIX_PROVIDER_KEY"]
    metrics = collect_metrics(
        cpu_cores=int(os.environ.get("GRIDIX_CPU_CORES", "1")),
        memory_mb=int(os.environ.get("GRIDIX_MEMORY_MB", "512")),
        bench_image=os.environ.get("GRIDIX_BENCH_IMAGE") or None,
    )
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {provider_key}"}) as client:
        report = await submit_benchmark(client, base_url, provider_key, metrics)
    print(json.dumps({"submitted": metrics, "validated": report.get("validated")}))


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    asyncio.run(_main())
