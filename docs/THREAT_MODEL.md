# GRIDIX Confidential Compute — Threat Model (Session 9.7)

Jobs run on **untrusted, provider-owned machines**. This document states, per data tier,
what a malicious provider (the host running the container) can and cannot see. We do **not
overpromise**: below the TEE tier, a determined host operator can read job data. Choose the
tier that matches your data's sensitivity.

The adversary is the **provider host**: root on the machine, able to inspect container
memory, disk, environment, and network. The coordinator is trusted (it holds the KEK and
brokers keys); Session 10+ hardens against a cheating provider economically, not
cryptographically.

> **Scope: this document describes the async JOBS path only.** Every guarantee below is
> implemented for jobs (`matcher`, `crypto` envelope encryption, `key_broker`, attestation).
> The synchronous inference path (`/v1/chat/completions`, `/v1/images/generations`) does
> **not** implement any of it: there is no envelope encryption, no DEK, and no
> attestation-gated release on that path — the prompt is sent to the selected node in
> cleartext. Because of that, `/v1/chat/completions` **refuses `data_tier=confidential_tee`
> with 501** rather than appear to honor a guarantee it cannot keep; other tiers on the
> chat path are served as `public` (plaintext visible to the host). Do not read the
> `confidential_tee` row as applying to chat or image inference.

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
- **Current enforcement is weaker than the guarantee above, and this is a stand-in, not
  the finished tier.** Three gaps to close before it can be relied on:
  - `attestation.verify_attestation` only checks an HMAC over the quote; it does **not**
    check the reported `measurement` against an allowlist, so any measurement with a valid
    signature is accepted. Real SGX/SEV verification pins the measurement to a known-good
    enclave image.
  - `tee_attested` is a **persistent flag** set at `/agent/attest` and cleared only on a
    later failed attestation. It is **not re-verified at dispatch/key-release time on the
    inference path**, so a node that attested once and then stopped running the enclave can
    still be selected until it submits a failing quote. (The jobs path re-checks in
    `key_broker` at key release; the inference path has no such gate — which is one reason
    chat refuses the tier.)
  - The tier is **not enforced on the inference path** at all (see the Scope note above).

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
