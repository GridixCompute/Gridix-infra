"""Provider benchmarking & validation (Sessions 11.1-11.2, 11.5).

At onboarding the agent runs a hardware benchmark (GPU probe, FLOPs/throughput, memory
bandwidth, disk/network) and submits a *signed* report. The coordinator validates the
measured numbers against the provider's declared capabilities — catching a machine that
claims an A100 but benchmarks like a weaker or absent GPU — and derives a performance tier
that the matcher can trust over self-reported specs.

The signature binds the report to the provider key that produced it (HMAC), and the
canonical-JSON encoding makes it deterministic/verifiable.
"""

import hashlib
import hmac

from app.fraud_proof import canonical_evidence

# A benchmark whose GPU FLOPs fall below this fraction of the claimed tier is rejected.
_MIN_GPU_RATIO = 0.6
# Reference throughput (TFLOPs) by GPU family, for validation.
GPU_REFERENCE_TFLOPS = {"A100": 19.5, "H100": 67.0, "V100": 7.0, "T4": 8.1, "L4": 30.3}


def sign_report(metrics: dict, provider_key: str) -> str:
    """Sign a benchmark report's metrics with the provider key (HMAC-SHA256)."""
    return hmac.new(provider_key.encode(), canonical_evidence(metrics), hashlib.sha256).hexdigest()


def verify_signature(metrics: dict, signature: str, provider_key: str) -> bool:
    """Verify a report signature was produced by ``provider_key``."""
    return hmac.compare_digest(signature, sign_report(metrics, provider_key))


def validate_benchmark(metrics: dict, declared_gpu_model: str | None) -> tuple[bool, str]:
    """Check measured numbers against the declared hardware (Session 11.2).

    Returns ``(ok, reason)``. A provider claiming a GPU it can't benchmark to is rejected.
    """
    if declared_gpu_model:
        reference = GPU_REFERENCE_TFLOPS.get(declared_gpu_model)
        measured = metrics.get("gpu_tflops")
        if reference is not None:
            if not isinstance(measured, int | float) or measured <= 0:
                return False, "claims a GPU but reported no GPU throughput"
            if measured < reference * _MIN_GPU_RATIO:
                return False, (
                    f"measured {measured} TFLOPs is far below {declared_gpu_model} (~{reference})"
                )
    return True, "ok"


def performance_tier(metrics: dict) -> str:
    """Derive a coarse performance tier from measured throughput (Session 11.5)."""
    tflops = float(metrics.get("gpu_tflops") or 0)
    if tflops >= 40:
        return "high"
    if tflops >= 8:
        return "mid"
    if tflops > 0:
        return "low"
    return "cpu"
