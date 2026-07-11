"""Secret management abstraction (Session 12.1).

Secrets come from the environment today (12-factor); the same interface fronts Vault or a
cloud KMS in production, with scoped access and rotation. No secret is ever written to the
repo, an image, or a log — this module only *reads* them by name at runtime. Key rotation
is zero-downtime via ``Settings.all_keks`` (a new key becomes primary while retired keys
still decrypt existing ciphertext; see :func:`app.crypto.decrypt_rotating`).
"""

import os
from typing import Protocol


class SecretManager(Protocol):
    """Reads named secrets at runtime."""

    def get(self, name: str) -> str | None: ...


class EnvSecretManager:
    """Reads secrets from the environment (``GRIDIX_`` prefixed)."""

    def get(self, name: str) -> str | None:
        return os.environ.get(name) or os.environ.get(f"GRIDIX_{name}")


class VaultSecretManager:  # pragma: no cover - requires a live Vault/KMS
    """Seam for HashiCorp Vault / cloud KMS with scoped access + rotation."""

    def __init__(self, addr: str, token: str) -> None:
        raise NotImplementedError("configure a real Vault/KMS backend in production")

    def get(self, name: str) -> str | None:
        raise NotImplementedError


_manager: SecretManager = EnvSecretManager()


def get_secret_manager() -> SecretManager:
    return _manager


def set_secret_manager(manager: SecretManager) -> None:
    global _manager
    _manager = manager
