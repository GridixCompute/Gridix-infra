"""Secret management abstraction (Session 12.1).

Secrets are read by name at runtime from a pluggable backend; no secret is ever written to
the repo, an image, or a log. Two backends are real and testable:

* ``env``  — 12-factor: values injected as ``GRIDIX_``-prefixed environment variables.
* ``file`` — Docker/Kubernetes secrets: each value in its own file under ``secret_dir``
  (e.g. ``/run/secrets/GRIDIX_KEK``). File permissions provide scoped access, and rotating a
  mounted secret needs no image rebuild.

* ``vault`` — HashiCorp Vault (KV v2): all managed secrets in one path, read once at startup
  after an AppRole/token login (never the root token). The highest-value secret — the
  coordinator private key, which can debit every developer's escrow — is meant to live here,
  not in ``.env`` where it would be lost or leaked with the box. See ``docs/VAULT.md``.

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


def _secret_name_candidates(name: str) -> tuple[str, ...]:
    """Callers ask by field name (``coordinator_private_key``) or env name (``GRIDIX_SECRET_KEY``);
    stores hold keys in either style. Resolve both, preferring an exact match."""
    return (name, name.upper(), f"GRIDIX_{name}", f"GRIDIX_{name}".upper())


class VaultSecretManager:
    """Reads secrets from HashiCorp Vault (KV v2). Fills the 12.1 seam.

    All managed secrets live in ONE KV-v2 secret at ``<mount>/data/<path>``; each Vault key is
    the env-style name (e.g. ``GRIDIX_COORDINATOR_PRIVATE_KEY``). The backend authenticates once
    (AppRole preferred, or a TTL token — never the root token) and reads that single path, whose
    values are cached in memory. The bound Vault policy must grant read on exactly that path and
    nothing else (no write, no list) — least privilege for a process that only consumes secrets.

    Construction performs the login + read eagerly, so a missing/unreachable Vault, a failed
    auth, or an absent path fails fast at startup (``SecretConfigurationError``) rather than on a
    later request. No secret value is ever placed in an exception message, log line, or repr.
    """

    def __init__(self, settings: Settings) -> None:
        try:
            import hvac  # lazy: only needed when secret_backend == "vault"
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without the extra
            raise SecretConfigurationError(
                "GRIDIX_SECRET_BACKEND=vault needs the 'vault' extra: pip install '.[vault]'"
            ) from exc

        if not settings.vault_addr:
            raise SecretConfigurationError(
                "GRIDIX_SECRET_BACKEND=vault but GRIDIX_VAULT_ADDR unset"
            )

        client = hvac.Client(url=settings.vault_addr, namespace=settings.vault_namespace or None)
        try:
            self._authenticate(client, settings)
            if not client.is_authenticated():
                raise SecretConfigurationError("Vault authentication failed (check role/token)")
            resp = client.secrets.kv.v2.read_secret_version(
                mount_point=settings.vault_kv_mount,
                path=settings.vault_secret_path,
                raise_on_deleted_version=True,
            )
        except SecretConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any hvac/transport error, sans secrets
            raise SecretConfigurationError(
                f"cannot read secrets from Vault at {settings.vault_addr} "
                f"({settings.vault_kv_mount}/{settings.vault_secret_path}): {type(exc).__name__}"
            ) from None
        data = resp.get("data", {}).get("data", {})
        if not isinstance(data, dict) or not data:
            raise SecretConfigurationError(
                f"Vault secret {settings.vault_kv_mount}/{settings.vault_secret_path} is empty"
            )
        self._cache: dict[str, str] = {str(k): str(v) for k, v in data.items()}
        self._addr = settings.vault_addr
        self._path = f"{settings.vault_kv_mount}/{settings.vault_secret_path}"
        # Drop the client so no live token lingers; the values are already cached.
        client.token = None

    @staticmethod
    def _authenticate(client, settings: Settings) -> None:
        if settings.vault_auth_method == "approle":
            if not settings.vault_role_id or not settings.vault_secret_id:
                raise SecretConfigurationError(
                    "vault_auth_method=approle needs GRIDIX_VAULT_ROLE_ID and _SECRET_ID"
                )
            client.auth.approle.login(
                role_id=settings.vault_role_id, secret_id=settings.vault_secret_id
            )
        elif settings.vault_auth_method == "token":
            if not settings.vault_token:
                raise SecretConfigurationError("vault_auth_method=token needs GRIDIX_VAULT_TOKEN")
            client.token = settings.vault_token
        else:  # pragma: no cover - Literal already constrains this
            raise SecretConfigurationError(
                f"unknown vault_auth_method {settings.vault_auth_method}"
            )

    def get(self, name: str) -> str | None:
        for candidate in _secret_name_candidates(name):
            if candidate in self._cache:
                return self._cache[candidate]
        return None

    def __repr__(self) -> str:  # never expose cached secret values
        return f"VaultSecretManager(addr={self._addr!r}, path={self._path!r})"


def build_secret_manager(settings: Settings) -> SecretManager:
    """Construct the configured backend, or fail fast with a clear message."""
    backend = settings.secret_backend
    if backend == "env":
        return EnvSecretManager()
    if backend == "file":
        return FileSecretManager(settings.secret_dir)
    if backend == "vault":
        return VaultSecretManager(settings)
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
