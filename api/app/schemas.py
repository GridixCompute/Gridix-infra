"""Pydantic v2 request/response schemas — the API contract.

Schemas reject illegal input at the edge so handlers only ever see valid data. Grouped
by session: registration & health (S1), jobs & providers (S2), agent (S3/S4).
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import JobKind, JobStatus


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
class RegisterDeveloperRequest(BaseModel):
    """Register a new developer account."""

    name: str = Field(min_length=1, max_length=200)


class RegisterProviderRequest(BaseModel):
    """Register a new provider account."""

    name: str = Field(min_length=1, max_length=200)
    region: str | None = Field(default=None, max_length=64)


class RegisteredPrincipal(BaseModel):
    """Response to a successful registration. ``api_key`` is returned exactly once."""

    id: uuid.UUID
    name: str
    api_key: str = Field(description="Store this now — it is never shown again.")


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
