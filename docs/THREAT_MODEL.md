# GRIDIX Confidential Compute — Threat Model (Session 9.7)

Jobs run on **untrusted, provider-owned machines**. This document states, per data tier,
what a malicious provider (the host running the container) can and cannot see. We do **not
overpromise**: below the TEE tier, a determined host operator can read job data. Choose the
tier that matches your data's sensitivity.

The adversary is the **provider host**: root on the machine, able to inspect container
memory, disk, environment, and network. The coordinator is trusted (it holds the KEK and
brokers keys); Session 10+ hardens against a cheating provider economically, not
cryptographically.

| Tier | Input/result confidentiality vs. a malicious host | Enforcement in code |
|---|---|---|
| `public` (default) | **None.** Plaintext input/result are visible to the host. | No encryption; any capable provider (`matcher`). |
| `encrypted_at_rest` | Ciphertext **at rest and in transit**; the coordinator stores only ciphertext. But the host still sees plaintext **in memory at runtime** (the DEK is brokered to the agent to decrypt for the container). | `crypto` envelope encryption (9.2); DEK brokered only to the assigned, in-flight provider (9.3, `key_broker.release_data_key`). |
| `confidential_tee` | Plaintext exists **only inside an attested enclave**; the host cannot read enclave memory. The DEK is released **only after a valid remote attestation**. | TEE-only scheduling (9.4, `matcher`); attestation-gated key release (9.5, `attestation.verify_attestation` + `key_broker`); confidential-tee never assigned to non-attested providers. |

## What each tier defends against

### `public`
- **Confidentiality:** none. Assume the provider reads everything.
- **Use for:** open data, public models, non-sensitive batch work.

### `encrypted_at_rest`
- **Defends:** coordinator compromise / storage leak (only ciphertext is stored),
  network interception (ciphertext in transit), and other tenants (content-addressed,
  per-job DEK).
- **Does NOT defend:** the executing host at runtime. To run the container, the agent
  receives the DEK (9.3) and decrypts — so a malicious host can dump plaintext from memory
  or the decrypted input file. **This tier trusts the executing provider with runtime
  plaintext.**
- **Key hygiene:** the DEK is job-scoped, released only to the assigned provider, only
  while the job is in flight, and is not available once the job ends (verified by tests).

### `confidential_tee`
- **Defends:** additionally, the executing host at runtime. Plaintext lives only inside a
  hardware enclave (SGX/SEV); the DEK is released **only** after the coordinator verifies a
  remote attestation quote (9.5), and confidential jobs are scheduled **only** to
  attested-TEE providers (9.4). Revoking attestation immediately cuts off the key.
- **Does NOT defend:** side-channel attacks against the TEE itself, or a compromised TEE
  vendor root of trust. Attestation reduces to trusting the hardware vendor.
- **Assumption:** the attestation verifier (`attestation_secret`, standing in for the
  vendor root) is sound. Production replaces the HMAC stand-in with real SGX/SEV quote
  verification.

## Runtime secrets (9.6)

Job-scoped credentials are short-lived, minted on demand, never persisted server-side, and
never logged (only their names). They expire on their own and are unavailable once the job
ends. Under `public`/`encrypted_at_rest`, a malicious host can still read injected secrets
from container memory — scope and rotate accordingly; under `confidential_tee` they are
protected by the enclave.

## Verification

These guarantees are exercised by the Session 9 test suite: envelope encryption + tamper
detection (`test_session9_crypto`), assigned-only/lifetime-only key brokering
(`test_session9_key_broker`), TEE-only scheduling (`test_session9_tee_scheduling`),
attestation-gated key release (`test_session9_attestation`), and non-persisted, job-scoped
secrets (`test_session9_secrets`).
