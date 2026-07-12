"""Secret management abstraction (Session 12.1).

Secrets are read by name at runtime from a pluggable backend; no secret is ever written to
the repo, an image, or a log. Two backends are real and testable:

* ``env``  — 12-factor: values injected as ``GRIDIX_``-prefixed environment variables.
* ``file`` — Docker/Kubernetes secrets: each value in its own file under ``secret_dir``
  (e.g. ``/run/secrets/GRIDIX_KEK``). File permissions provide scoped access, and rotating a
  mounted secret needs no image rebuild.

A ``vault`` backend (HashiCorp Vault / cloud KMS) is a documented seam, deliberately not
implemented here: shipping an unexercised client into the key path would be worse than an
honest, fail-fast "not configured". Selecting it raises at startup, not mid-request.

``init_secrets`` is the one entrypoint: it installs the backend, overlays any file/vault
secrets onto ``Settings`` (so all existing code keeps reading ``settings.kek`` etc.), and
validates that a non-dev deployment isn't running on insecure defaults — failing fast at
second zero rather than on the thousandth request. Zero-downtime key rotation is handled
separately via ``Settings.all_keks`` + :func:`app.crypto.decrypt_rotating`.
"""

import os
from pathlib import Path
from typing import Protocol

from loguru import logger

from app.config import Settings

# The env default that is safe ONLY for local dev and must never reach a real deployment.
_INSECURE_SECRET_KEY = "dev-insecure-secret-change-me"

# Secret settings sourced through the manager, mapped to their env/file lookup name.
_MANAGED_SECRETS = {
    "secret_key": "GRIDIX_SECRET_KEY",
    "kek": "GRIDIX_KEK",
    "kek_previous": "GRIDIX_KEK_PREVIOUS",
    "attestation_secret": "GRIDIX_ATTESTATION_SECRET",
}


class SecretConfigurationError(RuntimeError):
    """Raised at startup when the secret backend or required secrets are misconfigured."""


class SecretManager(Protocol):
    """Reads named secrets at runtime."""

    def get(self, name: str) -> str | None: ...


class EnvSecretManager:
    """Reads secrets from the environment (accepts a bare or ``GRIDIX_``-prefixed name)."""

    def get(self, name: str) -> str | None:
        return os.environ.get(name) or os.environ.get(f"GRIDIX_{name}")


class FileSecretManager:
    """Reads each secret from its own file under ``root`` (Docker/K8s secrets).

    Looks up ``root/<name>`` then ``root/GRIDIX_<name>``; a trailing newline (as ``echo`` and
    most secret stores add) is stripped. A missing file is a miss (``None``), never an error.
    """

    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def get(self, name: str) -> str | None:
        for candidate in (name, f"GRIDIX_{name}"):
            path = self._root / candidate
            if path.is_file():
                return path.read_text(encoding="utf-8").rstrip("\n")
        return None


def build_secret_manager(settings: Settings) -> SecretManager:
    """Construct the configured backend, or fail fast with a clear message."""
    backend = settings.secret_backend
    if backend == "env":
        return EnvSecretManager()
    if backend == "file":
        return FileSecretManager(settings.secret_dir)
    if backend == "vault":
        raise SecretConfigurationError(
            "GRIDIX_SECRET_BACKEND=vault is a documented seam that is not implemented in this "
            "build. Inject secrets via env (GRIDIX_SECRET_BACKEND=env) or files "
            "(GRIDIX_SECRET_BACKEND=file) until a live Vault/KMS exists to test against."
        )
    raise SecretConfigurationError(f"unknown secret backend {backend!r}")


def _overlay_managed_secrets(settings: Settings, manager: SecretManager) -> None:
    """Populate secret settings from the backend so downstream code reads them normally.

    For the ``env`` backend this re-reads what Pydantic already loaded (a no-op); for ``file``
    /``vault`` it is how mounted/brokered secrets reach ``Settings`` without leaking into the
    environment. Only non-empty values override — an absent secret leaves the default in place
    for :func:`validate_secret_config` to catch.
    """
    for field, lookup in _MANAGED_SECRETS.items():
        value = manager.get(lookup)
        if value:
            setattr(settings, field, value)


def validate_secret_config(settings: Settings) -> None:
    """Fail fast if a non-dev deployment is missing required secrets or uses dev defaults.

    Outside ``dev`` the coordinator must be given real secrets: the API-key HMAC
    (``secret_key``) is load-bearing on every authenticated request, the KEK (``kek``) gates
    per-job data-key brokering, and the attestation secret is the TEE root of trust. Booting
    on the baked-in defaults would silently make API keys forgeable and data protection
    ineffective. Every problem is reported at once so it is fixed in one pass.
    """
    if settings.env == "dev":
        return
    problems: list[str] = []
    if not settings.secret_key or settings.secret_key == _INSECURE_SECRET_KEY:
        problems.append("GRIDIX_SECRET_KEY is unset or the insecure dev default")
    if not settings.kek:
        problems.append("GRIDIX_KEK is unset (required for per-job data-key brokering)")
    if not settings.attestation_secret:
        problems.append("GRIDIX_ATTESTATION_SECRET is unset (TEE attestation root of trust)")
    if problems:
        raise SecretConfigurationError(
            f"refusing to start in env={settings.env!r} with insecure secret config: "
            + "; ".join(problems)
        )


def init_secrets(settings: Settings) -> None:
    """Install the secret backend, overlay its secrets onto ``settings``, and validate.

    Call once at process startup (API + scheduler). Raises :class:`SecretConfigurationError`
    fast if anything is misconfigured, so a broken deployment dies at second zero.
    """
    manager = build_secret_manager(settings)
    set_secret_manager(manager)
    _overlay_managed_secrets(settings, manager)
    validate_secret_config(settings)
    logger.info("secrets initialized (backend={}, env={})", settings.secret_backend, settings.env)


_manager: SecretManager = EnvSecretManager()


def get_secret_manager() -> SecretManager:
    return _manager


def set_secret_manager(manager: SecretManager) -> None:
    global _manager
    _manager = manager
