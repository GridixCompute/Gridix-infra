"""Fraud-proof-friendly evidence encoding (Session 10.7).

Dispute evidence is serialized *canonically* — deterministic JSON (sorted keys, no
insignificant whitespace) — and committed to with a sha256 hash. The same evidence always
yields the same bytes and the same commitment on any machine, so the record could later be
posted to (or verified by) an on-chain staking/slashing contract without ambiguity. This
module is forward-compat plumbing; nothing here is chain-specific.
"""

import hashlib
import json
from typing import Any


def canonical_evidence(evidence: dict[str, Any]) -> bytes:
    """Return the canonical, deterministic byte serialization of ``evidence``."""
    return json.dumps(
        evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode()


def evidence_commitment(evidence: dict[str, Any]) -> str:
    """Return the sha256 commitment over the canonical evidence (on-chain-ready)."""
    return hashlib.sha256(canonical_evidence(evidence)).hexdigest()
