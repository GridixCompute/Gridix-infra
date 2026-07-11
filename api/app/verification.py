"""Verification pipeline — decide whether to trust a submitted result.

Verification is *probabilistic*, not perfect. The design goal is to make cheating have
negative expected value: a provider cannot tell a canary from real work, canaries are
checked against a known answer, high-value work is cross-checked by quorum, and any
caught cheat is slashed for more than it could gain. Documented assumptions:

* The coordinator knows the correct output of every canary it injects.
* Result blobs are content-addressed (sha256), so a proof's ``output_sha256`` is
  cross-checkable against the stored ref and against other providers' outputs.
* Checks are pluggable per job class; today: proof well-formedness, exit/timeout, and
  (for canaries) an exact output-hash match. Approximate/schema checks slot in here.
"""

from dataclasses import dataclass

from app.models import Job, JobKind
from app.schemas import AgentResultRequest


@dataclass(frozen=True)
class Verdict:
    """The outcome of verifying one submitted result."""

    valid: bool
    reason: str
    is_canary: bool
    canary_passed: bool | None = None


def _proof_well_formed(req: AgentResultRequest) -> bool:
    """A proof must carry an exit code, and an output hash whenever a result is claimed."""
    if "exit_code" not in req.proof:
        return False
    return not (req.result_ref is not None and "output_sha256" not in req.proof)


def verify(job: Job, req: AgentResultRequest) -> Verdict:
    """Return a :class:`Verdict` for ``req`` against ``job``.

    Standard jobs are valid when the proof is well-formed, the container exited 0, and it
    did not time out. Canary jobs additionally require the output hash to match the known
    answer — a mismatch is the signal of a cheating provider.
    """
    is_canary = job.kind is JobKind.canary

    if not _proof_well_formed(req):
        return Verdict(False, "malformed_proof", is_canary, False if is_canary else None)
    if req.timed_out:
        return Verdict(False, "timeout", is_canary, False if is_canary else None)
    if req.exit_code != 0:
        return Verdict(False, "nonzero_exit", is_canary, False if is_canary else None)

    if is_canary:
        claimed = req.proof.get("output_sha256")
        passed = job.expected_output_hash is not None and claimed == job.expected_output_hash
        return Verdict(passed, "canary_pass" if passed else "canary_fail", True, passed)

    return Verdict(True, "ok", False, None)
