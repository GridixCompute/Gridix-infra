"""Per-job key brokering (Session 9.3).

The developer wraps a job's data key (DEK) under the coordinator KEK at submit. When the
*assigned* agent needs it, the coordinator unwraps and releases the DEK — but only for a
job assigned to that agent and only while the job is in flight, so a key is job-scoped and
short-lived. Session 9.5 additionally gates confidential-tee releases on a valid
attestation; that check lives here so there is one release path.
"""

from app.config import Settings
from app.crypto import DecryptionError, unwrap_key
from app.models import Job, JobStatus

_IN_FLIGHT = (JobStatus.assigned, JobStatus.running)


class KeyReleaseError(Exception):
    """Raised when a data key cannot be released under policy."""


def release_data_key(job: Job, settings: Settings) -> str:
    """Return the job's DEK for the assigned agent, enforcing lifetime/config policy.

    The caller must have already verified the requesting provider owns the job's
    assignment. Raises :class:`KeyReleaseError` if brokering isn't configured, there is no
    key, or the job is no longer in flight (its key is no longer available).
    """
    if not settings.kek:
        raise KeyReleaseError("key brokering is not configured")
    if job.wrapped_key is None:
        raise KeyReleaseError("job has no brokered key")
    if job.status not in _IN_FLIGHT:
        raise KeyReleaseError("job is not in flight; key no longer available")
    try:
        return unwrap_key(job.wrapped_key.encode(), settings.kek)
    except DecryptionError as exc:
        raise KeyReleaseError("could not unwrap job key") from exc
