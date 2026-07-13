"""Conversion between ledger amounts (``Decimal`` whole USDC) and raw token units (``int``).

USDC is 6-decimal, so 1 USDC == 1_000_000 units. Money is never a float. Converting a ledger
amount to units truncates toward zero at the token's precision (a fractional micro-USDC can't be
moved on-chain); the truncated dust stays in the off-chain ledger and reconciliation accounts for
it, so nothing is silently lost.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal


def to_units(amount: Decimal, decimals: int) -> int:
    """Whole-USDC ``Decimal`` → raw integer units, truncated toward zero."""
    if amount < 0:
        raise ValueError(f"amount must be non-negative, got {amount}")
    scale = Decimal(10) ** decimals
    return int((amount * scale).to_integral_value(rounding=ROUND_DOWN))


def from_units(units: int, decimals: int) -> Decimal:
    """Raw integer units → whole-USDC ``Decimal`` (exact)."""
    return Decimal(units) / (Decimal(10) ** decimals)
