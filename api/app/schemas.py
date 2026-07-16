"""Pydantic v2 request/response schemas — the API contract.

Schemas reject illegal input at the edge so handlers only ever see valid data. Grouped
by session: registration & health (S1), jobs & providers (S2), agent (S3/S4).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import DataTier, JobKind, JobStatus


class ORMModel(BaseModel):
    """Base for response models read directly from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


# ── Health ────────────────────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    """Result of the liveness/readiness probe."""

    status: Literal["ok", "degraded"]
    database: bool
    redis: bool


# ── Registration (Session 1) ────────────────────────────────────────────────────
# The ``__gridix_`` prefix is reserved for internal principals (e.g. the canary-owning
# system developer). Refusing it at registration means no attacker can register a
# look-alike name to hijack canaries (security wave 0 / H12).
_RESERVED_NAME_PREFIX = "__gridix_"


def _reject_reserved_name(name: str) -> str:
    if name.strip().lower().startswith(_RESERVED_NAME_PREFIX):
        raise ValueError("name uses a reserved system prefix")
    return name


class RegisterDeveloperRequest(BaseModel):
    """Register a new developer account."""

    name: str = Field(min_length=1, max_length=200)

    _no_reserved = field_validator("name")(_reject_reserved_name)


class RegisterProviderRequest(BaseModel):
    """Register a new provider account."""

    name: str = Field(min_length=1, max_length=200)
    region: str | None = Field(default=None, max_length=64)

    _no_reserved = field_validator("name")(_reject_reserved_name)


class RegisteredPrincipal(BaseModel):
    """Response to a successful registration. ``api_key`` is returned exactly once."""

    id: uuid.UUID
    name: str
    api_key: str = Field(description="Store this now — it is never shown again.")


# ── Wallet sign-in (SIWE / EIP-4361) ────────────────────────────────────────────
class NonceResponse(BaseModel):
    """A challenge to sign. ``message`` is composed server-side and must be signed
    byte-for-byte — the client never assembles the text it authenticates with."""

    nonce: str
    message: str
    expires_at: datetime


class VerifyRequest(BaseModel):
    """A signed challenge. ``nonce`` selects the stored message to check the signature
    against; the message text itself is never accepted from the client."""

    address: str = Field(max_length=42)
    # 65-byte secp256k1 signature as 0x-hex. Bounded so a huge body can't reach the
    # recovery path at all (same reflex as the bearer-length cap, pentest L1).
    signature: str = Field(max_length=200)
    nonce: str = Field(max_length=64)


class SessionResponse(BaseModel):
    """An established wallet session. ``api_key`` is the session credential: it goes
    straight into the httpOnly cookie and is never shown to the user."""

    developer_id: uuid.UUID
    name: str
    wallet_address: str
    api_key: str
    expires_at: datetime


class ApiKeyResponse(ORMModel):
    """A programmatic key as listed in /settings. The secret is NOT included — it is
    returned once, by the create call, and never again."""

    id: uuid.UUID
    label: str | None
    prefix: str
    revoked: bool
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None


class CreateApiKeyRequest(BaseModel):
    """Mint a programmatic key for the agent/API."""

    label: str = Field(min_length=1, max_length=80)


class CreatedApiKey(BaseModel):
    """The one and only time a programmatic key's plaintext is returned."""

    id: uuid.UUID
    label: str | None
    prefix: str
    api_key: str = Field(description="Store this now — it is never shown again.")


# ── Inference (/v1) ─────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    """One turn. OpenAI-shaped so existing clients work unchanged."""

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)


class ChatCompletionRequest(BaseModel):
    """A chat request. Bounded at the edge: these numbers size the balance gate, and an
    unbounded max_tokens would make the worst case unknowable."""

    model: str = Field(min_length=1, max_length=128)
    messages: list[ChatMessage] = Field(min_length=1, max_length=256)
    max_tokens: int | None = Field(default=None, ge=1, le=32_768)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    # Fixing the seed makes a reply reproducible, which is what lets a canary compare a
    # node's answer against a known-good one.
    seed: int | None = Field(default=None, ge=0)
    stream: bool = False
    data_tier: DataTier = DataTier.public


class ChatUsage(BaseModel):
    """Tokens the request actually consumed — what it is billed on."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ChatCompletionResponse(BaseModel):
    """A completed chat request, with what it cost and which node served it."""

    model: str
    content: str
    usage: ChatUsage
    cost_usdc: Decimal
    provider_id: uuid.UUID


class ImageGenerationRequest(BaseModel):
    """An image request."""

    model: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=4_000)
    n: int = Field(default=1, ge=1, le=8)
    seed: int | None = Field(default=None, ge=0)
    data_tier: DataTier = DataTier.public


class ImageGenerationResponse(BaseModel):
    """Generated images, billed per image actually returned."""

    model: str
    images: list[str]
    cost_usdc: Decimal
    provider_id: uuid.UUID


class ModelInfo(BaseModel):
    """A catalogue model and whether the network is serving it right now."""

    id: str
    modality: str
    available: bool
    nodes: int
    input_usdc_per_mtok: Decimal
    output_usdc_per_mtok: Decimal
    usdc_per_image: Decimal
    context_window: int


class ModelsResponse(BaseModel):
    """Everything GRIDIX can serve, with prices."""

    models: list[ModelInfo]


# ── Resource spec & jobs (Session 2) ────────────────────────────────────────────
class ResourceSpec(BaseModel):
    """Hardware a job needs. The scheduler matches these against provider capabilities."""

    model_config = ConfigDict(extra="forbid")

    cpu_cores: int = Field(default=1, ge=1, le=256)
    memory_mb: int = Field(default=512, ge=64, le=1_048_576)
    gpu: bool = False
    gpu_vram_mb: int = Field(default=0, ge=0, le=1_048_576)


class JobArgs(BaseModel):
    """Optional container overrides for the job."""

    model_config = ConfigDict(extra="forbid")

    command: list[str] | None = None
    env: dict[str, str] | None = None


class SubmitJobRequest(BaseModel):
    """Submit a job for execution."""

    model_config = ConfigDict(extra="forbid")

    image_ref: str = Field(min_length=1, max_length=512)
    input_ref: str | None = Field(default=None, max_length=512)
    resource_spec: ResourceSpec = Field(default_factory=ResourceSpec)
    args: JobArgs | None = None
    allow_egress: bool = False
    timeout_seconds: int = Field(default=300, gt=0, le=86_400)
    is_high_value: bool = False
    redundancy: int = Field(default=1, ge=1, le=9)
    # Endpoint-style job: the HTTP port the container listens on (Session 7.5).
    exposed_port: int | None = Field(default=None, ge=1, le=65535)
    # Data-handling policy tier (Session 9). Invalid values are rejected here.
    data_tier: Literal["public", "encrypted_at_rest", "confidential_tee"] = "public"
    # Per-job data key wrapped under the coordinator KEK, for brokering (Session 9.3).
    wrapped_key: str | None = Field(default=None, max_length=512)


class JobResponse(ORMModel):
    """A job as seen by its developer."""

    id: uuid.UUID
    developer_id: uuid.UUID
    kind: JobKind
    status: JobStatus
    image_ref: str
    input_ref: str | None
    result_ref: str | None
    resource_spec: dict[str, Any]
    allow_egress: bool
    timeout_seconds: int
    is_high_value: bool
    redundancy: int
    exposed_port: int | None
    data_tier: str
    assigned_provider_id: uuid.UUID | None
    attempt_count: int
    lease_expires_at: datetime | None
    escrow_amount: float | None
    cost_final: float | None
    created_at: datetime
    updated_at: datetime


class EndpointInfo(BaseModel):
    """The coordinator-issued routed URL + capability token for an endpoint job."""

    url: str
    token: str
    port: int


# ── Providers (Session 2) ───────────────────────────────────────────────────────
class ProviderCapabilities(BaseModel):
    """Capabilities a provider declares. All fields optional on PATCH (partial update)."""

    model_config = ConfigDict(extra="forbid")

    region: str | None = Field(default=None, max_length=64)
    gpu_model: str | None = Field(default=None, max_length=120)
    gpu_vram_mb: int | None = Field(default=None, ge=0)
    cpu_cores: int | None = Field(default=None, ge=0)
    memory_mb: int | None = Field(default=None, ge=0)
    max_concurrent: int | None = Field(default=None, ge=1)


class ProviderResponse(ORMModel):
    """A provider's own view of itself."""

    id: uuid.UUID
    name: str
    region: str | None
    gpu_model: str | None
    gpu_vram_mb: int
    cpu_cores: int
    memory_mb: int
    max_concurrent: int
    reputation: float
    enabled: bool
    degraded: bool
    connected_at: datetime | None
    last_seen: datetime | None
    path_type: str | None
    created_at: datetime


class PingResponse(BaseModel):
    """Presence status returned to an agent keepalive (Session 7.1)."""

    connected: bool
    connected_at: datetime | None
    last_seen: datetime | None


class BandwidthResponse(BaseModel):
    """Per-provider byte counters, lifetime and for the current session (Session 7.7)."""

    ingress_bytes: int
    egress_bytes: int
    total_bytes: int
    session_ingress_bytes: int
    session_egress_bytes: int


class ProviderJobAttempt(BaseModel):
    """One execution this provider ran, for the provider job-history view (Session 11.6).

    Joins the attempt to its parent job so a provider sees what it worked on, how it
    turned out, and how long it took — without exposing another developer's job payload.
    """

    attempt_id: uuid.UUID
    job_id: uuid.UUID
    attempt_number: int
    outcome: str
    job_status: JobStatus
    image_ref: str
    is_high_value: bool
    redundancy: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None


class ReputationEventResponse(ORMModel):
    """One entry in a provider's reputation ledger — why the score moved (Session 11.6)."""

    id: uuid.UUID
    job_id: uuid.UUID | None
    kind: str
    delta: float
    score_after: float
    meta: dict[str, Any] | None
    created_at: datetime


# ── Path negotiation (Session 7.4) ──────────────────────────────────────────────
class IceCandidate(BaseModel):
    """A single ICE-style connectivity candidate advertised by the agent."""

    address: str = Field(max_length=64)
    port: int = Field(ge=1, le=65535)
    kind: Literal["host", "srflx", "relay"] = "host"


class AgentPathReport(BaseModel):
    """Agent reports its NAT classification + candidates so the coordinator can decide
    whether a direct path is possible or the relay must be used."""

    nat_type: Literal["open", "restricted", "symmetric"]
    candidates: list[IceCandidate] = Field(default_factory=list, max_length=16)


class PathResponse(BaseModel):
    """The negotiated path for the provider's current session."""

    path_type: Literal["direct", "relay"]


class CacheReport(BaseModel):
    """Agent reports the digests it currently has cached (Session 8.5)."""

    cached: list[str] = Field(default_factory=list, max_length=10000)


class PeerFetchPlan(BaseModel):
    """Where a provider should fetch an artifact from (Session 8.7)."""

    enabled: bool
    kind: Literal["origin", "peer"]
    provider_id: uuid.UUID | None = None
    seeders: list[uuid.UUID] = Field(default_factory=list)


class DataKeyResponse(BaseModel):
    """The brokered per-job data key released to the assigned agent (Session 9.3)."""

    data_key: str


class BenchmarkSubmit(BaseModel):
    """A signed benchmark report submitted at onboarding (Session 11.1)."""

    metrics: dict[str, Any]
    signature: str = Field(min_length=1, max_length=64)


class HealthReport(BaseModel):
    """Telemetry an agent reports periodically (Session 11.4)."""

    gpu_temp_c: float | None = None
    throttling: bool = False
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_ms: float | None = None


class HealthResult(BaseModel):
    """The evaluated health verdict for a reported sample."""

    degraded: bool
    reason: str


class BenchmarkResponse(ORMModel):
    """A stored benchmark report."""

    id: uuid.UUID
    provider_id: uuid.UUID
    metrics: dict[str, Any]
    signature: str
    validated: bool
    created_at: datetime


class AttestationQuote(BaseModel):
    """A TEE attestation quote submitted by the agent (Session 9.5)."""

    measurement: str = Field(max_length=256)
    signature: str = Field(max_length=256)


class AttestationResult(BaseModel):
    """Whether the submitted attestation was accepted."""

    attested: bool


class JobSecretsResponse(BaseModel):
    """Short-lived, job-scoped secrets injected into the container (Session 9.6)."""

    secrets: dict[str, str]
    expires_at: int


# ── Disputes (Session 10) ───────────────────────────────────────────────────────
class DisputeResponse(ORMModel):
    """A slash dispute with its reproducible evidence."""

    id: uuid.UUID
    provider_id: uuid.UUID
    job_id: uuid.UUID | None
    amount: float
    state: str
    reason: str
    evidence: dict[str, Any] | None
    evidence_hash: str | None
    ruling_reason: str | None
    created_at: datetime
    resolved_at: datetime | None


class DisputeRuling(BaseModel):
    """An operator's manual decision on a dispute (Session 10.4)."""

    upheld: bool
    reason: str = Field(min_length=1, max_length=256)


# ── Agent protocol (Session 3/4) ────────────────────────────────────────────────
class AgentJob(ORMModel):
    """Everything an agent needs to run one assigned job."""

    id: uuid.UUID
    image_ref: str
    input_ref: str | None
    resource_spec: dict[str, Any]
    args: dict[str, Any] | None
    allow_egress: bool
    timeout_seconds: int
    exposed_port: int | None
    lease_expires_at: datetime | None


class AgentPollResponse(BaseModel):
    """Poll result — a job to run, or ``job=null`` when the queue for this provider is
    empty."""

    job: AgentJob | None = None


class HeartbeatRequest(BaseModel):
    """Extend the lease on an in-flight job."""

    job_id: uuid.UUID


class HeartbeatResponse(BaseModel):
    """The renewed lease deadline."""

    job_id: uuid.UUID
    lease_expires_at: datetime


class AgentStatusRequest(BaseModel):
    """Agent reports it has started executing (``running``)."""

    status: Literal["running"]


class AgentResultRequest(BaseModel):
    """Agent submits a terminal result (Session 4)."""

    result_ref: str | None = None
    exit_code: int
    proof: dict[str, Any]
    timed_out: bool = False


class Ack(BaseModel):
    """Generic acknowledgement with the resulting job status."""

    job_id: uuid.UUID
    status: JobStatus


class BlobRef(BaseModel):
    """A stored blob's content-addressed ref and size."""

    ref: str
    size: int


# ── Resumable uploads (Session 8.4) ─────────────────────────────────────────────
class UploadCreateRequest(BaseModel):
    """Start a resumable upload, optionally declaring the final sha256 for verification."""

    digest: str | None = Field(default=None, min_length=64, max_length=64)


class UploadSessionResponse(BaseModel):
    """An upload session's state, including bytes received (the resume offset)."""

    upload_id: uuid.UUID
    received: int
    blob_ref: str | None = None


# ── Audit (Session 6) ───────────────────────────────────────────────────────────
class AttemptRecord(ORMModel):
    """One execution attempt in a job's audit trail."""

    provider_id: uuid.UUID | None
    attempt_number: int
    outcome: str
    result_ref: str | None
    started_at: datetime | None
    finished_at: datetime | None


class LedgerRecord(ORMModel):
    """One ledger row in a job's audit trail."""

    account: str
    account_ref: uuid.UUID | None
    direction: str
    amount: float
    reason: str
    created_at: datetime


class JobAudit(BaseModel):
    """The full audit trail for one job: lifecycle, attempts, and money movements."""

    job: JobResponse
    attempts: list[AttemptRecord]
    ledger: list[LedgerRecord]


# ── Billing (Session 10) ────────────────────────────────────────────────────────
class BillingLedgerEntry(ORMModel):
    """One double-entry ledger row across the developer's jobs (Session 10.1).

    Every leg is returned raw — the frontend groups by ``entry_group`` to show that
    each transaction balances (sum of debits == sum of credits). Numbers are never
    "tidied" client-side; a mismatch is a bug to surface, not to hide.
    """

    id: uuid.UUID
    entry_group: uuid.UUID
    job_id: uuid.UUID | None
    account: str
    direction: str
    amount: float
    reason: str
    created_at: datetime


class BillingSummary(BaseModel):
    """Authoritative period totals derived from the ledger (Session 10.3).

    ``total_spent == provider_paid + protocol_fees + data_costs``. All values are
    computed on the backend so the UI shows exact, auditable figures.
    """

    total_spent: float
    provider_paid: float
    protocol_fees: float
    data_costs: float
    total_refunded: float
    total_held: float
    total_escrowed: float
    job_count: int
    balanced: bool
