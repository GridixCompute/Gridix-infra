#!/usr/bin/env python3
"""Live proof of the production coordinator wiring (Vault + startup address assertion).

Exercises the REAL startup path against a live Vault, wired to the PRODUCTION contract addresses:

  init_secrets()  -> VaultSecretManager reads secrets (incl. the coordinator key) from Vault
  install_chain() -> builds the production Web3ChainClient, fetching the coordinator key from the
                     manager (never from Settings/env), then verify_coordinator_address() asserts
                     the derived address == GRIDIX_EXPECTED_COORDINATOR_ADDRESS.

Then it shows the fail-fast: a wrong expected address raises before anything is installed. No
transaction is sent; the coordinator key is never printed. Config comes from the environment.

Run: see smoke/vault/README (env: GRIDIX_SECRET_BACKEND=vault + vault creds + chain_* + prod addrs).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

from app.chain.bootstrap import install_chain, verify_coordinator_address  # noqa: E402
from app.config import Settings  # noqa: E402
from app.secret_manager import init_secrets  # noqa: E402


def main() -> None:
    settings = Settings()
    assert settings.secret_backend == "vault", "must run with GRIDIX_SECRET_BACKEND=vault"
    assert settings.chain_enabled, "must run with GRIDIX_CHAIN_ENABLED=true"
    expected = settings.expected_coordinator_address
    assert expected, "must set GRIDIX_EXPECTED_COORDINATOR_ADDRESS (the on-chain role holder)"
    print(f"expected coordinator (prod role holder): {expected}")
    print(f"escrow={settings.escrow_address}\nstaking={settings.staking_address}\n")

    # 1) real startup: read secrets from Vault, then build the production client + assert address.
    init_secrets(settings)  # VaultSecretManager installed; coordinator key NOT put on Settings
    assert settings.coordinator_private_key.get_secret_value() == "", "coord key leaked to Settings"
    client = install_chain(settings)  # fetches key from Vault, verifies address, installs
    assert client is not None
    assert client.coordinator_address == expected.lower(), "derived address != expected"
    print("OK  coordinator key read from Vault; derived address == expected prod role holder ✓")
    print("OK  coordinator key absent from Settings (fetched on demand) ✓")

    # 2) fail-fast: a wrong expected address must refuse to start.
    try:
        verify_coordinator_address(
            client.coordinator_address, "0x000000000000000000000000000000000000dEaD"
        )
    except ValueError as exc:
        assert "refusing to start" in str(exc)
        print(f"OK  mismatch fails fast: {exc}")
    else:
        raise SystemExit("!! wrong expected address did NOT fail fast")

    print("\nPRODUCTION COORDINATOR WIRING PROVEN (Vault read + startup address assertion) ✓")


if __name__ == "__main__":
    main()
