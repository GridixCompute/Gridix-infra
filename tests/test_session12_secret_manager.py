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


def test_vault_backend_fails_fast() -> None:
    """The Vault/KMS seam is not implemented — selecting it raises at build, not at use."""
    with pytest.raises(SecretConfigurationError, match="vault"):
        build_secret_manager(Settings(env="dev", secret_backend="vault"))


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
