#!/usr/bin/env python3
"""Live DoD verification for the Vault secret backend (run against a real Vault).

Usage:
  verify_live.py up     # Vault reachable: secrets read from Vault, key off Settings, least-priv
  verify_live.py down   # Vault killed:   init_secrets must FAIL FAST, not boot with empty keys

Config comes from the environment (as a real deployment would):
  GRIDIX_SECRET_BACKEND=vault GRIDIX_VAULT_ADDR=... GRIDIX_VAULT_AUTH_METHOD=approle
  GRIDIX_VAULT_ROLE_ID=... GRIDIX_VAULT_SECRET_ID=... GRIDIX_ENV=prod

This script must NEVER print a secret value — it prints only assertions and masked markers, so
its captured output can be grepped to prove the coordinator key never leaks.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

from app.config import Settings  # noqa: E402
from app.secret_manager import (  # noqa: E402
    SecretConfigurationError,
    get_secret_manager,
    init_secrets,
)

# What provision.sh wrote — used only to ASSERT equality, never printed.
EXPECT_SECRET_KEY = "SENTINEL_secret_key_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
EXPECT_COORD_PREFIX = "0xC00RD1NAT0R"  # full value asserted from Vault; only a hint is shown


def _up() -> None:
    settings = Settings()
    assert settings.secret_backend == "vault", "not configured for vault"
    # Before init, Settings has only the insecure default — proves the real value comes from Vault.
    assert settings.secret_key == "dev-insecure-secret-change-me"
    init_secrets(settings)  # authenticates to Vault, reads the path, overlays, validates

    assert settings.secret_key == EXPECT_SECRET_KEY, "secret_key did not come from Vault"
    print("OK  secret_key overlaid from Vault (not env)")

    # The coordinator key is the crown jewel: it must NOT be overlaid onto Settings...
    assert settings.coordinator_private_key.get_secret_value() == "", (
        "coord key leaked into Settings"
    )
    print("OK  coordinator key absent from Settings (fetched on demand only)")

    # ...but the backend can fetch it from Vault when it needs to sign.
    key = get_secret_manager().get("coordinator_private_key")
    assert key and key.startswith(EXPECT_COORD_PREFIX), "coordinator key not readable from Vault"
    print(
        f"OK  coordinator key readable from Vault (len={len(key)}, starts {EXPECT_COORD_PREFIX}…)"
    )

    _least_privilege(settings)
    print("\nUP CHECKS PASSED ✓")


def _least_privilege(settings: Settings) -> None:
    """The backend's AppRole token may READ its path and nothing else — prove write/other-path
    are denied (403), so a compromised backend can't tamper with or enumerate secrets."""
    import hvac
    from hvac.exceptions import Forbidden, InvalidPath

    client = hvac.Client(url=settings.vault_addr)
    client.auth.approle.login(role_id=settings.vault_role_id, secret_id=settings.vault_secret_id)
    assert client.is_authenticated()

    try:
        client.secrets.kv.v2.create_or_update_secret(path="gridix", secret={"x": "y"})
        raise SystemExit("!! backend token could WRITE its secret — policy too broad")
    except Forbidden:
        print("OK  write to own path denied (403) — read-only enforced")

    try:
        client.secrets.kv.v2.read_secret_version(path="other-app", raise_on_deleted_version=True)
        raise SystemExit("!! backend token could read another path — policy too broad")
    except (Forbidden, InvalidPath):
        print("OK  read of a different path denied — least privilege enforced")


def _down() -> None:
    settings = Settings()
    try:
        init_secrets(settings)
    except SecretConfigurationError as exc:
        assert EXPECT_SECRET_KEY not in str(exc), "error message leaked a secret"
        print(f"OK  init_secrets FAILED FAST with a clear message: {exc}")
        print("\nDOWN CHECK PASSED ✓ (refused to boot; did not run with empty keys)")
        return
    raise SystemExit("!! init_secrets did NOT fail when Vault was down — would boot insecure")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "up"
    {"up": _up, "down": _down}[mode]()
