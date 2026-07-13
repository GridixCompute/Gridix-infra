"""Session 12.1 — secret backend selection, file secrets, and fail-fast validation.

Proves the P2 hardening: a non-dev deployment refuses to boot on insecure defaults, the
``file`` backend (Docker/K8s secrets) is read and overlaid onto settings, and the
unimplemented ``vault`` seam fails at startup rather than mid-request.
"""

import pytest
from app.config import Settings
from app.secret_manager import (
    EnvSecretManager,
    FileSecretManager,
    SecretConfigurationError,
    build_secret_manager,
    init_secrets,
    set_secret_manager,
    validate_secret_config,
)

_REAL = {
    "secret_key": "a-real-32-char-minimum-secret-value",
    "kek": "real-kek",
    "attestation_secret": "real-att",
}


@pytest.fixture(autouse=True)
def _restore_manager():
    """init_secrets installs a global manager; restore the default after each test."""
    yield
    set_secret_manager(EnvSecretManager())


def _settings(**overrides) -> Settings:
    base = dict(env="prod", **_REAL)
    base.update(overrides)
    return Settings(**base)


def test_dev_allows_insecure_defaults() -> None:
    """Local dev may run on the baked-in defaults — validation is a no-op there."""
    validate_secret_config(Settings(env="dev", secret_key="dev-insecure-secret-change-me", kek=""))


def test_prod_rejects_insecure_defaults() -> None:
    """A non-dev deployment on dev defaults/empties fails fast, naming every problem."""
    settings = _settings(secret_key="dev-insecure-secret-change-me", kek="", attestation_secret="")
    with pytest.raises(SecretConfigurationError) as exc:
        validate_secret_config(settings)
    msg = str(exc.value)
    assert "GRIDIX_SECRET_KEY" in msg
    assert "GRIDIX_KEK" in msg
    assert "GRIDIX_ATTESTATION_SECRET" in msg


def test_prod_accepts_real_secrets() -> None:
    """Real secrets in a non-dev env validate cleanly."""
    validate_secret_config(_settings())


def test_env_backend_is_default() -> None:
    assert isinstance(build_secret_manager(Settings(env="dev")), EnvSecretManager)


def test_vault_backend_requires_addr() -> None:
    """Selecting vault without an address fails fast at build, not mid-request."""
    with pytest.raises(SecretConfigurationError, match="VAULT_ADDR"):
        build_secret_manager(Settings(env="dev", secret_backend="vault", vault_addr=""))


def test_file_secret_manager_reads_and_strips(tmp_path) -> None:
    (tmp_path / "GRIDIX_KEK").write_text("secret-value\n")  # trailing newline, as echo adds
    mgr = FileSecretManager(str(tmp_path))
    assert mgr.get("GRIDIX_KEK") == "secret-value"
    assert mgr.get("GRIDIX_MISSING") is None


def test_file_backend_overlays_secrets_and_validates(tmp_path) -> None:
    """init_secrets with the file backend loads mounted secrets onto settings, then passes
    validation using those values — not the (empty) env defaults it started with."""
    (tmp_path / "GRIDIX_SECRET_KEY").write_text("file-sourced-secret-key-value")
    (tmp_path / "GRIDIX_KEK").write_text("file-sourced-kek")
    (tmp_path / "GRIDIX_ATTESTATION_SECRET").write_text("file-sourced-att")
    settings = Settings(
        env="prod",
        secret_backend="file",
        secret_dir=str(tmp_path),
        secret_key="dev-insecure-secret-change-me",  # would fail validation if not overlaid
        kek="",
        attestation_secret="",
    )
    init_secrets(settings)  # must not raise
    assert settings.secret_key == "file-sourced-secret-key-value"
    assert settings.kek == "file-sourced-kek"
    assert settings.attestation_secret == "file-sourced-att"


def test_init_secrets_fails_fast_on_missing_file_secrets(tmp_path) -> None:
    """File backend with nothing mounted → the defaults survive → validation refuses to boot."""
    settings = Settings(
        env="prod",
        secret_backend="file",
        secret_dir=str(tmp_path),
        secret_key="dev-insecure-secret-change-me",
        kek="",
        attestation_secret="",
    )
    with pytest.raises(SecretConfigurationError):
        init_secrets(settings)


# ── Vault backend (12.1 seam, now real; hvac mocked so the suite stays hermetic) ─────────────
from unittest.mock import MagicMock, patch  # noqa: E402

from app.secret_manager import VaultSecretManager  # noqa: E402

_COORD_KEY = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
_VAULT_DATA = {
    "GRIDIX_SECRET_KEY": "vault-sourced-secret-key-value",
    "GRIDIX_KEK": "vault-sourced-kek",
    "GRIDIX_ATTESTATION_SECRET": "vault-sourced-att",
    "GRIDIX_COORDINATOR_PRIVATE_KEY": _COORD_KEY,
}


def _fake_client(data=None, *, authenticated=True, read_error: Exception | None = None):
    client = MagicMock()
    client.is_authenticated.return_value = authenticated
    if read_error is not None:
        client.secrets.kv.v2.read_secret_version.side_effect = read_error
    else:
        client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": data or {}}}
    return client


def _vault_settings(**overrides) -> Settings:
    base = {
        "env": "prod",
        "secret_backend": "vault",
        "vault_addr": "http://127.0.0.1:8200",
        "vault_auth_method": "token",
        "vault_token": "s.not-a-root-token",
    }
    base.update(overrides)
    return Settings(**base)


def test_vault_reads_secrets_by_field_and_env_name() -> None:
    """A managed lookup (GRIDIX_SECRET_KEY) and a bare field lookup (coordinator_private_key)
    both resolve from the single KV secret."""
    with patch("hvac.Client", return_value=_fake_client(_VAULT_DATA)):
        mgr = VaultSecretManager(_vault_settings())
    assert mgr.get("GRIDIX_SECRET_KEY") == "vault-sourced-secret-key-value"
    assert mgr.get("coordinator_private_key") == _COORD_KEY
    assert mgr.get("GRIDIX_MISSING") is None


def test_vault_init_secrets_overlays_and_validates() -> None:
    """init_secrets over Vault populates settings from Vault (not env) and passes validation;
    the coordinator key stays out of Settings, reachable only via the manager."""
    settings = _vault_settings(secret_key="dev-insecure-secret-change-me", kek="")
    with patch("hvac.Client", return_value=_fake_client(_VAULT_DATA)):
        init_secrets(settings)
    assert settings.secret_key == "vault-sourced-secret-key-value"
    assert settings.kek == "vault-sourced-kek"
    # the coordinator key was never overlaid onto Settings — fetched on demand instead
    assert settings.coordinator_private_key.get_secret_value() == ""
    from app.secret_manager import get_secret_manager

    assert get_secret_manager().get("coordinator_private_key") == _COORD_KEY


def test_vault_fails_fast_when_unreachable() -> None:
    """A down/unreachable Vault raises at startup — and the message carries no secret."""
    boom = ConnectionError("connection refused")
    with (
        patch("hvac.Client", return_value=_fake_client(read_error=boom)),
        pytest.raises(SecretConfigurationError) as exc,
    ):
        VaultSecretManager(_vault_settings())
    assert _COORD_KEY not in str(exc.value)
    assert "Vault" in str(exc.value)


def test_vault_fails_fast_on_auth_failure() -> None:
    with (
        patch("hvac.Client", return_value=_fake_client(_VAULT_DATA, authenticated=False)),
        pytest.raises(SecretConfigurationError, match="authentication failed"),
    ):
        VaultSecretManager(_vault_settings())


def test_vault_approle_requires_role_and_secret_id() -> None:
    settings = _vault_settings(vault_auth_method="approle", vault_role_id="", vault_secret_id="")
    with (
        patch("hvac.Client", return_value=_fake_client(_VAULT_DATA)),
        pytest.raises(SecretConfigurationError, match="approle"),
    ):
        VaultSecretManager(settings)


def test_vault_empty_secret_rejected() -> None:
    with (
        patch("hvac.Client", return_value=_fake_client({})),
        pytest.raises(SecretConfigurationError, match="empty"),
    ):
        VaultSecretManager(_vault_settings())


def test_vault_manager_repr_hides_secret_values() -> None:
    """repr must never expose the cache — a stray logger.info(manager) can't leak the key."""
    with patch("hvac.Client", return_value=_fake_client(_VAULT_DATA)):
        mgr = VaultSecretManager(_vault_settings())
    text = repr(mgr)
    assert "127.0.0.1:8200" in text
    assert _COORD_KEY not in text
    assert "vault-sourced-secret-key-value" not in text


def test_coordinator_key_masked_in_settings_repr() -> None:
    """Even if the key is injected via env, a repr of Settings shows it masked (SecretStr)."""
    settings = Settings(env="dev", coordinator_private_key=_COORD_KEY)
    assert _COORD_KEY not in repr(settings)
    assert settings.coordinator_private_key.get_secret_value() == _COORD_KEY
