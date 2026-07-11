"""Job pricing — cost as a function of resources and duration.

Escrow is taken at submit time against the worst case (the full timeout), then the
final cost is computed from the actual run duration and the remainder refunded. This
guarantees a developer is never charged more than they agreed to and never charged for
time the job did not consume.
"""

from decimal import ROUND_HALF_UP, Decimal

from app.config import Settings

_CENT = Decimal("0.00000001")
_GPU_MULTIPLIER = Decimal(4)  # GPU-seconds are priced above CPU-seconds


def compute_cost(resource_spec: dict, duration_seconds: float, settings: Settings) -> Decimal:
    """Return the cost for a run of ``duration_seconds`` using ``resource_spec``.

    Cost scales with cpu cores (and a GPU premium) times duration in minutes, anchored on
    ``base_job_price`` (price per cpu-core-minute).
    """
    cpu = max(1, int(resource_spec.get("cpu_cores", 1)))
    gpu = bool(resource_spec.get("gpu", False))
    minutes = Decimal(str(max(0.0, duration_seconds))) / Decimal(60)
    unit = Decimal(str(settings.base_job_price))
    multiplier = _GPU_MULTIPLIER if gpu else Decimal(1)
    cost = unit * Decimal(cpu) * multiplier * minutes
    return cost.quantize(_CENT, rounding=ROUND_HALF_UP)


def escrow_estimate(resource_spec: dict, timeout_seconds: int, settings: Settings) -> Decimal:
    """Worst-case cost held in escrow at submit (the full timeout budget)."""
    return compute_cost(resource_spec, float(timeout_seconds), settings)


def protocol_fee(cost: Decimal, settings: Settings) -> Decimal:
    """The protocol's cut of a settled job, in the same currency as ``cost``."""
    fee = cost * Decimal(settings.protocol_fee_bps) / Decimal(10_000)
    return fee.quantize(_CENT, rounding=ROUND_HALF_UP)
