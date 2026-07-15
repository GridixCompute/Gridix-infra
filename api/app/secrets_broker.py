"""Runtime secret injection (Session 9.6).

A job may need short-lived, job-scoped credentials at runtime (e.g. a token to read its
own inputs). The coordinator mints them on demand and hands them to the *assigned* agent,
which injects them into the container as env vars and drops them on completion. Nothing is
persisted and values are never logged — only their names.

The minted token is deterministically scoped to the job id and a time window, so it is
useless for any other job and expires on its own. A production build fetches real scoped
credentials from a secret manager (Vault/KMS, Session 12.1) behind this same interface.
"""

import hashlib
import hmac
import time
import uuid

from app.config import Settings
from app.models import DataTier, Job, JobStatus

_IN_FLIGHT = (JobStatus.assigned, JobStatus.running)


class SecretReleaseError(Exception):
    """Raised when secrets cannot be released under policy."""


def _job_token(job_id: uuid.UUID, window: int, secret_key: str) -> str:
    msg = f"jobsecret:{job_id}:{window}".encode()
    return hmac.new(secret_key.encode(), msg, hashlib.sha256).hexdigest()


def mint_job_secrets(
    job: Job, settings: Settings, *, now: int | None = None
) -> tuple[dict[str, str], int]:
    """Mint the job's short-lived scoped secrets; return ``(secrets, expires_at_epoch)``.

    Raises :class:`SecretReleaseError` if the job is no longer in flight.
    """
    if job.status not in _IN_FLIGHT:
        raise SecretReleaseError("job is not in flight; secrets no longer available")
    now = int(time.time()) if now is None else now
    ttl = settings.secrets_ttl_seconds
    window = now // ttl
    secrets = {
        "GRIDIX_JOB_ID": str(job.id),
        "GRIDIX_JOB_TOKEN": _job_token(job.id, window, settings.endpoint_signing_key),
    }
    if job.data_tier is not DataTier.public:
        secrets["GRIDIX_DATA_TIER"] = str(job.data_tier)
    return secrets, (window + 1) * ttl
