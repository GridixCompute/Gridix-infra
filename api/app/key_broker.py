"""Per-job key brokering (Session 9.3).

The developer wraps a job's data key (DEK) under the coordinator KEK at submit. When the
*assigned* agent needs it, the coordinator unwraps and releases the DEK — but only for a
job assigned to that agent and only while the job is in flight, so a key is job-scoped and
short-lived. Session 9.5 additionally gates confidential-tee releases on a valid
attestation; that check lives here so there is one release path.
"""

from app.config import Settings
from app.crypto import DecryptionError, decrypt_rotating
from app.models import DataTier, Job, JobStatus, Provider

_IN_FLIGHT = (JobStatus.assigned, JobStatus.running)


class KeyReleaseError(Exception):
    """Raised when a data key cannot be released under policy."""


def release_data_key(job: Job, provider: Provider, settings: Settings) -> str:
    """Return the job's DEK for the assigned agent, enforcing lifetime/policy.

    The caller must have already verified the requesting provider owns the job's
    assignment. Raises :class:`KeyReleaseError` if brokering isn't configured, there is no
    key, the job is no longer in flight, or — for a confidential-tee job — the provider
    has no valid TEE attestation (Session 9.5).
    """
    if not settings.kek:
        raise KeyReleaseError("key brokering is not configured")
    if job.wrapped_key is None:
        raise KeyReleaseError("job has no brokered key")
    if job.status not in _IN_FLIGHT:
        raise KeyReleaseError("job is not in flight; key no longer available")
    if job.data_tier is DataTier.confidential_tee and not provider.tee_attested:
        raise KeyReleaseError("provider has no valid TEE attestation")
    try:
        # Accept any active/retired KEK so a rotation doesn't strand in-flight jobs (12.1).
        return decrypt_rotating(job.wrapped_key.encode(), settings.all_keks).decode()
    except DecryptionError as exc:
        raise KeyReleaseError("could not unwrap job key") from exc
