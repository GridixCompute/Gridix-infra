"""Redundant execution quorum — agree on the truth when one provider isn't enough.

High-value jobs run on K providers. Their results are grouped by output hash; the group
with a strict majority wins. Providers in the winning group are paid and gain reputation;
providers that disagreed with a reached majority are slashed. If no output holds a
majority, the quorum is inconclusive and the job is failed (no one is paid for
unverifiable work). With K=1 this reduces to "trust the single result", so the same code
path serves dev and production.
"""

from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AttemptResult:
    """A single provider's contribution to a quorum."""

    provider_id: str
    output_hash: str | None  # None when the attempt produced no usable output
    succeeded: bool  # exit 0, no timeout, well-formed


@dataclass(frozen=True)
class QuorumOutcome:
    """The decision over a set of attempts."""

    reached: bool
    winning_hash: str | None
    agreers: list[str] = field(default_factory=list)  # provider ids in the majority
    disagreers: list[str] = field(default_factory=list)  # provider ids that dissented


def evaluate_quorum(attempts: list[AttemptResult], redundancy: int) -> QuorumOutcome:
    """Decide the winning output over ``attempts`` for a job needing ``redundancy`` votes.

    A hash wins only with a strict majority of the required votes (``> redundancy / 2``),
    which prevents a single result from being accepted for a job that demanded several.
    """
    usable = [a for a in attempts if a.succeeded and a.output_hash is not None]
    if not usable:
        return QuorumOutcome(reached=False, winning_hash=None)

    counts = Counter(a.output_hash for a in usable)
    winning_hash, votes = counts.most_common(1)[0]
    needed = redundancy // 2 + 1  # strict majority of required votes
    if votes < needed:
        return QuorumOutcome(reached=False, winning_hash=None)

    agreers = [a.provider_id for a in attempts if a.output_hash == winning_hash and a.succeeded]
    disagreers = [
        a.provider_id
        for a in attempts
        if a.provider_id not in agreers and (a.output_hash is not None or not a.succeeded)
    ]
    return QuorumOutcome(True, winning_hash, agreers, disagreers)
