"""The single authoritative job state machine.

Every status change goes through :func:`transition`. Nothing else may write
``Job.status`` — this is what keeps the lifecycle legal and consistently timestamped.

Legal transitions::

    queued    → assigned
    assigned  → running | queued (reassign) | failed | timeout
    running   → completed | failed | timeout | queued (reassign)
    completed | failed | timeout → (terminal)
"""

from datetime import UTC, datetime

from app.models import Job, JobStatus

# Adjacency map of legal transitions. Terminal states map to an empty set.
_LEGAL: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.queued: frozenset({JobStatus.assigned}),
    JobStatus.assigned: frozenset(
        {JobStatus.running, JobStatus.queued, JobStatus.failed, JobStatus.timeout}
    ),
    JobStatus.running: frozenset(
        {JobStatus.completed, JobStatus.failed, JobStatus.timeout, JobStatus.queued}
    ),
    JobStatus.completed: frozenset(),
    JobStatus.failed: frozenset(),
    JobStatus.timeout: frozenset(),
}

TERMINAL_STATES: frozenset[JobStatus] = frozenset(
    {JobStatus.completed, JobStatus.failed, JobStatus.timeout}
)


class IllegalTransitionError(ValueError):
    """Raised when a status change is not permitted by the state machine."""

    def __init__(self, current: JobStatus, target: JobStatus) -> None:
        super().__init__(f"illegal job transition: {current} → {target}")
        self.current = current
        self.target = target


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    """Return whether ``current → target`` is a legal transition."""
    return target in _LEGAL.get(current, frozenset())


def _now() -> datetime:
    return datetime.now(UTC)


def transition(job: Job, target: JobStatus) -> Job:
    """Move ``job`` to ``target``, enforcing legality and stamping lifecycle times.

    Args:
        job: The job to transition (mutated in place).
        target: The desired next status.

    Returns:
        The same job, updated.

    Raises:
        IllegalTransitionError: If the transition is not permitted.
    """
    if not can_transition(job.status, target):
        raise IllegalTransitionError(job.status, target)

    now = _now()
    job.status = target
    if target is JobStatus.queued:
        job.queued_at = now
        # A requeued job releases its provider and lease.
        job.assigned_provider_id = None
        job.lease_expires_at = None
    elif target is JobStatus.assigned:
        job.assigned_at = now
    elif target is JobStatus.running:
        job.started_at = now
    elif target in TERMINAL_STATES:
        job.finished_at = now
        job.lease_expires_at = None
    return job
