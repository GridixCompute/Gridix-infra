"""TEE remote attestation verification (Session 9.5).

Before a confidential-tee job's data key is released, the coordinator verifies the
provider's attestation quote — evidence that the code is running in a genuine, unmodified
enclave. Only a valid quote grants the ``tee_attested`` flag (and thus the key).

Real SGX/SEV attestation validates a hardware-signed quote against the vendor's root of
trust and checks the measurement against an allowlist — that lives on infra. Here the
quote is HMAC-signed under a trusted verifier secret (``attestation_secret``), which
exercises the same accept/reject control flow: a tampered or absent quote fails.
"""

import hashlib
import hmac

from app.config import Settings


def sign_measurement(measurement: str, secret: str) -> str:
    """Produce the quote signature for ``measurement`` (test/enclave helper)."""
    return hmac.new(secret.encode(), measurement.encode(), hashlib.sha256).hexdigest()


def verify_attestation(quote: dict, settings: Settings) -> bool:
    """Return whether ``quote`` is a valid attestation.

    A quote is ``{"measurement": ..., "signature": ...}``. Verification fails if the
    verifier isn't configured, the quote is malformed, or the signature doesn't match.
    """
    if not settings.attestation_secret:
        return False
    measurement = quote.get("measurement")
    signature = quote.get("signature")
    if not isinstance(measurement, str) or not isinstance(signature, str):
        return False
    expected = sign_measurement(measurement, settings.attestation_secret)
    return hmac.compare_digest(signature, expected)
