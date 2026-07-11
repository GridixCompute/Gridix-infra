"""Provider health evaluation from telemetry (Session 11.4).

Agents periodically report lightweight telemetry (GPU thermals/throttle, error rate,
latency). A provider is marked *degraded* when any signal crosses a threshold — a GPU that
starts throttling in production, a rising error rate, or an overheating card — so the
matcher can down-tier it (11.5) before it hurts real jobs.
"""

from app.config import Settings


def evaluate_degraded(sample: dict, settings: Settings) -> tuple[bool, str]:
    """Return ``(degraded, reason)`` for a telemetry sample."""
    if sample.get("throttling"):
        return True, "gpu throttling"
    temp = sample.get("gpu_temp_c")
    if isinstance(temp, int | float) and temp > settings.health_max_gpu_temp_c:
        return True, f"gpu temp {temp}C over {settings.health_max_gpu_temp_c}C"
    error_rate = float(sample.get("error_rate") or 0.0)
    if error_rate > settings.health_max_error_rate:
        return True, f"error rate {error_rate} over {settings.health_max_error_rate}"
    return False, "healthy"
