"""SQLAlchemy ORM models — the GRIDIX data model.

The schema is designed around the job state machine
(``queued → assigned → running → completed | failed | timeout``) with leases and
heartbeats for reliability. Money never touches crypto here: value moves through
``ledger_entries`` (double-entry) so fiat-now / on-chain-later is a swap.

Type choices are deliberately portable: ``Uuid`` is a native ``uuid`` on Postgres and
``CHAR(32)`` elsewhere; JSON columns are ``JSONB`` on Postgres and plain ``JSON`` on
SQLite (used only by the hermetic unit tests). Status/kind columns are non-native
enums (VARCHAR + Python ``Enum``) so migrations stay trivial to roll forward and back.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# JSONB on Postgres, JSON on every other dialect (hermetic SQLite tests).
JSONVariant = JSON().with_variant(JSONB, "postgresql")


class JobStatus(enum.StrEnum):
    """States in the job lifecycle. Transitions are enforced by ``app.state_machine``."""

    queued = "queued"
    assigned = "assigned"
    running = "running"
    completed = "completed"
    failed = "failed"
    timeout = "timeout"


class JobKind(enum.StrEnum):
    """Job classification. Canaries are indistinguishable from real work to providers."""

    standard = "standard"
    canary = "canary"


class OwnerType(enum.StrEnum):
    """Which principal an API key authenticates."""

    developer = "developer"
    provider = "provider"


class AttemptOutcome(enum.StrEnum):
    """Terminal (or in-flight) outcome of a single execution attempt."""

    assigned = "assigned"
    running = "running"
    completed = "completed"
    failed = "failed"
    timeout = "timeout"
    reassigned = "reassigned"


class LedgerDirection(enum.StrEnum):
    """Double-entry direction. Per group, sum(debit) == sum(credit)."""

    debit = "debit"
    credit = "credit"


class LedgerAccount(enum.StrEnum):
    """Accounts value can move between."""

    developer = "developer"
    provider = "provider"
    protocol = "protocol"
    escrow = "escrow"
    stake = "stake"
    disputed = "disputed"  # slashed stake held pending dispute resolution (Session 10)


class DisputeState(enum.StrEnum):
    """Lifecycle of a slash dispute (Session 10.1)."""

    open = "open"  # slash held; provider may contest within the window
    under_review = "under_review"  # contested; awaiting adjudication
    upheld = "upheld"  # slash confirmed → held stake burned to protocol
    overturned = "overturned"  # slash reversed → held stake returned to provider


class ReputationKind(enum.StrEnum):
    """Reasons a provider's reputation changed."""

    job_success = "job_success"
    job_failure = "job_failure"
    timeout = "timeout"
    canary_pass = "canary_pass"
    canary_fail = "canary_fail"
    quorum_agree = "quorum_agree"
    quorum_disagree = "quorum_disagree"
    dispute = "dispute"
    slash = "slash"


class PathType(enum.StrEnum):
    """How the coordinator reaches a provider: a direct P2P path or via the relay."""

    direct = "direct"
    relay = "relay"


class DataTier(enum.StrEnum):
    """Per-job data-handling policy (Session 9). Guarantees rise with the tier."""

    public = "public"  # no confidentiality guarantee (default)
    encrypted_at_rest = "encrypted_at_rest"  # coordinator stores ciphertext only
    confidential_tee = "confidential_tee"  # runs only on attested TEE hardware


class BandwidthDirection(enum.StrEnum):
    """Data-transfer direction, from the provider's perspective."""

    ingress = "ingress"  # bytes the provider received (e.g. input/model downloads)
    egress = "egress"  # bytes the provider sent (e.g. result uploads)


def _utcnow() -> datetime:
    """Timezone-aware UTC now — used as a client-side default so ORM objects carry the
    timestamp immediately (no lazy refresh during async response serialization)."""
    return datetime.now(UTC)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )


class Developer(Base):
    """A customer who submits jobs and is charged for verified compute."""

    __tablename__ = "developers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # On-chain wallet (GridixEscrow depositor) for the settlement layer (Session 13). Lowercase
    # 0x-hex; nullable so fiat-only developers keep working. Unique so one wallet maps to one dev.
    wallet_address: Mapped[str | None] = mapped_column(String(42), unique=True, index=True)
    created_at: Mapped[datetime] = _created_at()

    jobs: Mapped[list["Job"]] = relationship(back_populates="developer")


class Provider(Base):
    """A machine operator that rents out GPU/CPU by running the agent.

    Declared capabilities are explicit columns (not JSON) so the scheduler can filter
    on them cheaply. ``reputation`` is a running score maintained from
    ``reputation_events``; stake lives in the ledger, not here (single source of truth).
    """

    __tablename__ = "providers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str | None] = mapped_column(String(64))

    # Declared capabilities (Session 2 PATCH /providers/me).
    gpu_model: Mapped[str | None] = mapped_column(String(120))
    gpu_vram_mb: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cpu_cores: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    memory_mb: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_concurrent: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    reputation: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # On-chain wallet (GridixStaking staker / settlement payee) for Session 13. Lowercase 0x-hex.
    wallet_address: Mapped[str | None] = mapped_column(String(42), unique=True, index=True)

    # Confidential compute (Session 9.4-9.5): whether the provider has a currently-valid
    # TEE attestation. Set by the attestation flow; only these run confidential-tee jobs.
    tee_attested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Continuous health (Session 11.4): set when telemetry shows throttling/errors.
    degraded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Control-channel presence (Session 7.1). ``last_seen`` is bumped on every agent
    # call; ``connected_at`` marks the start of the current unbroken connection.
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    # Reachability path for the current session (Session 7.4): direct P2P or relay.
    path_type: Mapped[PathType | None] = mapped_column(
        Enum(PathType, name="path_type", native_enum=False, length=10)
    )
    path_established_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint("reputation >= 0", name="ck_provider_reputation_nonneg"),
        CheckConstraint("max_concurrent >= 1", name="ck_provider_max_concurrent"),
    )


class ApiKey(Base):
    """A hashed API credential. The plaintext is shown once at registration and never
    stored — only its keyed HMAC-SHA256 digest is persisted."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_type: Mapped[OwnerType] = mapped_column(
        Enum(OwnerType, name="owner_type", native_enum=False, length=20), nullable=False
    )
    developer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("developers.id", ondelete="CASCADE")
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE")
    )

    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # A wallet sign-in mints one of these as the browser session (label "session"), so the
    # UI and the agent CLI authenticate through the SAME path and require_developer needs
    # no second mechanism. NULL = never expires — what a user-generated CLI key is.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lets a developer tell their keys apart in /settings.
    label: Mapped[str | None] = mapped_column(String(80))

    created_at: Mapped[datetime] = _created_at()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Exactly one owner FK is populated (portable XOR: exactly one is non-null).
        CheckConstraint(
            "(developer_id IS NULL) <> (provider_id IS NULL)",
            name="ck_apikey_single_owner",
        ),
    )


class ProviderModel(Base):
    """A model a provider's node declares it can serve.

    Written by the relay when a node's tunnel comes up, so it is the coordinator's answer
    to "who can serve llama-3-70b right now?" — a query, not a per-process dict. That
    matters: the tunnels live in the relay, while any API replica may need to dispatch.
    A registry held in one process's memory would be right only in that process.

    Declared, not verified. A node claiming a model it does not run is exactly the
    substitution attack canaries exist to catch; this table records the claim.
    """

    __tablename__ = "provider_models"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (UniqueConstraint("provider_id", "model", name="uq_provider_model"),)


class AuthNonce(Base):
    """A single-use SIWE (EIP-4361) challenge.

    The server composes the ENTIRE message and stores it verbatim; the wallet signs that
    exact string and /auth/verify checks the signature against what was stored. Nothing
    the client sends is ever parsed into an authorization decision, so the classic SIWE
    failure modes — a forged ``domain``, a swapped ``chainId``, a rewritten address —
    cannot occur: those fields are ours, not theirs.

    Rows live in the database rather than Redis on purpose: a Redis outage is a
    degradation this system tolerates everywhere else (see docs/RUNBOOKS.md), and losing
    the ability to sign in is not a degradation.
    """

    __tablename__ = "auth_nonces"

    id: Mapped[uuid.UUID] = _uuid_pk()
    nonce: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # Lowercase 0x-hex. The address the challenge was issued to; verify() requires the
    # recovered signer to equal it, so a signature for someone else's challenge is useless.
    address: Mapped[str] = mapped_column(String(42), nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set the moment a nonce is spent. The UPDATE that sets it is guarded by
    # `used_at IS NULL`, so two concurrent replays cannot both win.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class Job(Base):
    """A unit of work: a Docker image + input + resource spec, moving through the
    state machine. Result and proof land here once a provider returns them."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    developer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("developers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[JobKind] = mapped_column(
        Enum(JobKind, name="job_kind", native_enum=False, length=20),
        default=JobKind.standard,
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", native_enum=False, length=20),
        default=JobStatus.queued,
        nullable=False,
        index=True,
    )

    # Work definition.
    image_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    input_ref: Mapped[str | None] = mapped_column(String(512))
    result_ref: Mapped[str | None] = mapped_column(String(512))
    resource_spec: Mapped[dict] = mapped_column(JSONVariant, nullable=False, default=dict)
    args: Mapped[dict | None] = mapped_column(JSONVariant)
    allow_egress: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)

    # Endpoint-style jobs (Session 7.5): the container port the coordinator routes to.
    exposed_port: Mapped[int | None] = mapped_column(Integer)

    # Data-handling policy tier (Session 9).
    data_tier: Mapped[DataTier] = mapped_column(
        Enum(DataTier, name="data_tier", native_enum=False, length=24),
        default=DataTier.public,
        nullable=False,
    )
    # The per-job data key (DEK), wrapped under the coordinator KEK (Session 9.3).
    wrapped_key: Mapped[str | None] = mapped_column(String(512))

    # Verification / redundancy (Session 5).
    is_high_value: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    redundancy: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    expected_output_hash: Mapped[str | None] = mapped_column(String(64))
    proof: Mapped[dict | None] = mapped_column(JSONVariant)

    # Scheduling / lease (Session 3).
    assigned_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("providers.id", ondelete="SET NULL"), index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Economics (Session 6). Escrow amount held at submit; cost finalized at settle.
    escrow_amount: Mapped[float | None] = mapped_column(Numeric(20, 8))
    cost_final: Mapped[float | None] = mapped_column(Numeric(20, 8))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))

    # Lifecycle timestamps, set by the transition helper.
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow,
        nullable=False,
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    developer: Mapped["Developer"] = relationship(back_populates="jobs")
    attempts: Mapped[list["JobAttempt"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("redundancy >= 1", name="ck_job_redundancy_positive"),
        CheckConstraint("timeout_seconds > 0", name="ck_job_timeout_positive"),
        # Idempotency is scoped per developer.
        UniqueConstraint("developer_id", "idempotency_key", name="uq_job_idempotency"),
        Index("ix_jobs_status_kind", "status", "kind"),
    )


class JobAttempt(Base):
    """One execution of a job on one provider. A high-value job with redundancy K has
    up to K concurrent attempts; a reassigned job accrues sequential attempts."""

    __tablename__ = "job_attempts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("providers.id", ondelete="SET NULL"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[AttemptOutcome] = mapped_column(
        Enum(AttemptOutcome, name="attempt_outcome", native_enum=False, length=20),
        default=AttemptOutcome.assigned,
        nullable=False,
    )

    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_ref: Mapped[str | None] = mapped_column(String(512))
    proof: Mapped[dict | None] = mapped_column(JSONVariant)

    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped["Job"] = relationship(back_populates="attempts")

    __table_args__ = (UniqueConstraint("job_id", "attempt_number", name="uq_attempt_number"),)


class LedgerEntry(Base):
    """A single row of a double-entry transaction. Rows sharing ``entry_group`` balance:
    sum of debits == sum of credits. Nothing is ever updated — corrections are new
    groups. This is the fiat-first money abstraction; on-chain settlement swaps the
    ``PaymentProvider`` behind it, not this table."""

    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = _uuid_pk()
    entry_group: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )

    account: Mapped[LedgerAccount] = mapped_column(
        Enum(LedgerAccount, name="ledger_account", native_enum=False, length=20), nullable=False
    )
    # Which developer/provider this account row belongs to (null for protocol).
    account_ref: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)

    direction: Mapped[LedgerDirection] = mapped_column(
        Enum(LedgerDirection, name="ledger_direction", native_enum=False, length=10),
        nullable=False,
    )
    amount: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)

    # The on-chain transaction this row came from, for rows that came from one. Null for
    # everything else — inference charges, fees, stake movements — which have no tx.
    #
    # The watcher already had it (chain_events dedups on tx_hash/log_index) and dropped it
    # on the way to the ledger, so a developer could see "+50 USDC" with no way to tie it
    # to the transfer they made. 0x-hex, 32 bytes.
    tx_hash: Mapped[str | None] = mapped_column(String(66), index=True)

    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_ledger_amount_nonneg"),
        Index("ix_ledger_account", "account", "account_ref"),
    )


class ReputationEvent(Base):
    """An append-only record of why a provider's reputation moved. The provider's
    running ``reputation`` score is derived by applying these deltas."""

    __tablename__ = "reputation_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[ReputationKind] = mapped_column(
        Enum(ReputationKind, name="reputation_kind", native_enum=False, length=24),
        nullable=False,
    )
    delta: Mapped[float] = mapped_column(Float, nullable=False)
    score_after: Mapped[float] = mapped_column(Float, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONVariant)

    created_at: Mapped[datetime] = _created_at()


class ProviderArtifact(Base):
    """Which content-addressed artifacts a provider currently has cached (Session 8.5).

    Reported by the agent; the scheduler soft-prefers providers that already hold a job's
    input digest so warm-cache placement avoids a re-download."""

    __tablename__ = "provider_artifacts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    digest: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (UniqueConstraint("provider_id", "digest", name="uq_provider_artifact"),)


class UploadSession(Base):
    """A resumable chunked-upload session (Session 8.4). Staged bytes live on disk keyed
    by this id; this row tracks ownership and the promoted blob ref on completion."""

    __tablename__ = "upload_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    developer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("developers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    declared_digest: Mapped[str | None] = mapped_column(String(64))
    blob_ref: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = _created_at()


class Dispute(Base):
    """A contested slash (Session 10). While open/under_review the slashed stake is HELD
    in the ``disputed`` ledger account, not burned; resolution burns or returns it."""

    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    state: Mapped[DisputeState] = mapped_column(
        Enum(DisputeState, name="dispute_state", native_enum=False, length=16),
        default=DisputeState.open,
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONVariant)
    # sha256 commitment over the canonical evidence — on-chain-ready (Session 10.7).
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    ruling_reason: Mapped[str | None] = mapped_column(String(256))
    window_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HealthSample(Base):
    """A periodic health/telemetry sample from a provider agent (Session 11.4)."""

    __tablename__ = "health_samples"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gpu_temp_c: Mapped[float | None] = mapped_column(Float)
    throttling: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = _created_at()


class AuditLogEntry(Base):
    """A tamper-evident, hash-chained audit record (Session 12.6).

    Each entry commits to the previous entry's hash, so any alteration or deletion breaks
    the chain and is detectable."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    seq: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict] = mapped_column(JSONVariant, nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class BenchmarkReport(Base):
    """A signed hardware benchmark a provider submits at onboarding (Session 11.1).

    Metrics are validated against declared capabilities (11.2) and drive performance tiers
    (11.5). The signature binds the report to the provider key that produced it."""

    __tablename__ = "benchmark_reports"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metrics: Mapped[dict] = mapped_column(JSONVariant, nullable=False)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    validated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Hardware fingerprint (e.g. GPU UUID) for anti-spoofing collision checks (11.6).
    hardware_fingerprint: Mapped[str | None] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = _created_at()


class BandwidthEvent(Base):
    """An append-only record of bytes moved to/from a provider (Session 7.7).

    Aggregated per provider (and per session via ``created_at`` since ``connected_at``)
    for observability and future bandwidth-based pricing."""

    __tablename__ = "bandwidth_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    direction: Mapped[BandwidthDirection] = mapped_column(
        Enum(BandwidthDirection, name="bandwidth_direction", native_enum=False, length=10),
        nullable=False,
    )
    num_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (CheckConstraint("num_bytes >= 0", name="ck_bandwidth_nonneg"),)


# ── On-chain settlement layer (Session 13) ─────────────────────────────────────────────
# These tables are the durable state the chain layer recovers from after a crash. The
# off-chain ledger stays the accounting source of truth; nothing here changes a balance —
# they record *intent to touch the chain* (settlements) and *observed chain facts* (events)
# so settlement is idempotent and the watcher survives reorgs.


class ChainTxStatus(enum.StrEnum):
    """Lifecycle of an outbound chain transaction (settleBatch / debit / depositSettlement)."""

    pending = "pending"  # row written, nonce reserved, NOT yet broadcast
    submitted = "submitted"  # broadcast; tx hash known, awaiting confirmations
    confirmed = "confirmed"  # mined and confirmed N deep — terminal success
    failed = "failed"  # reverted or permanently dropped — terminal failure


class ChainTxKind(enum.StrEnum):
    """What an outbound chain transaction does."""

    settle_batch = "settle_batch"  # GridixStaking.settleBatch — credit provider earnings
    deposit_settlement = "deposit_settlement"  # GridixStaking.depositSettlement — fund the pool
    debit = "debit"  # GridixEscrow.debit — pull consumed developer escrow to treasury


class ChainSettlement(Base):
    """One outbound aggregate chain transaction, recorded BEFORE broadcast (Session 13).

    This is the idempotency backbone: the ``batch_key`` is a deterministic id for the work a
    transaction represents, so a crash between "decide to send" and "confirmed" can never
    produce a second payout — recovery finds the existing row by key/nonce instead of building
    a fresh batch. ``nonce`` pins the account sequence so a stuck tx is replaced, not doubled.
    """

    __tablename__ = "chain_settlements"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[ChainTxKind] = mapped_column(
        Enum(ChainTxKind, name="chain_tx_kind", native_enum=False, length=24), nullable=False
    )
    status: Mapped[ChainTxStatus] = mapped_column(
        Enum(ChainTxStatus, name="chain_tx_status", native_enum=False, length=16),
        default=ChainTxStatus.pending,
        nullable=False,
        index=True,
    )
    # Deterministic idempotency key for the work this tx settles (e.g. sorted payee+amount set,
    # or "debit:<dev>:<epoch>"). Unique so the same work is never enqueued twice.
    batch_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    # Account nonce reserved for this tx (monotonic per coordinator EOA). Unique among live rows.
    nonce: Mapped[int | None] = mapped_column(BigInteger, index=True)
    tx_hash: Mapped[str | None] = mapped_column(String(66), unique=True, index=True)
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    # The payees + raw-unit amounts this tx pays (JSON: [[address, amount_units], ...]) so the
    # ledger can be marked settled only once the tx confirms.
    payload: Mapped[dict | None] = mapped_column(JSONVariant)
    error: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = _created_at()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderSettlement(Base):
    """How much of a provider's off-chain earnings has been pushed on-chain (Session 13).

    One row per (provider, settlement) leg — the source of "already settled on-chain" used to
    compute the next batch and to reconcile against ``staking.earningsOf`` + withdrawn. Written
    in the same transaction that confirms the parent ``ChainSettlement`` so the two never drift.
    """

    __tablename__ = "provider_settlements"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    settlement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chain_settlements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_units: Mapped[int] = mapped_column(BigInteger, nullable=False)  # raw USDC units
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (CheckConstraint("amount_units >= 0", name="ck_provsettle_nonneg"),)


class ChainEvent(Base):
    """An observed on-chain log the watcher has seen (Session 13).

    Deduplicated by (tx_hash, log_index). ``confirmed`` flips only once the event's block is
    ``chain_confirmations`` deep; ``processed`` flips once its side effect (e.g. crediting a
    developer's ledger on Deposit) has been applied. ``block_hash`` lets the watcher detect a
    reorg (same number, different hash) and roll back anything applied on the orphaned block.
    """

    __tablename__ = "chain_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    block_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    address: Mapped[str] = mapped_column(String(42), nullable=False)
    args: Mapped[dict | None] = mapped_column(JSONVariant)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (UniqueConstraint("tx_hash", "log_index", name="uq_chain_event_log"),)


class ChainCursor(Base):
    """The watcher's high-water mark: the last block fully scanned for a given stream.

    A single-row-per-stream table so a restart resumes from where it left off instead of
    rescanning from genesis. ``block_hash`` of the cursor head is kept to anchor reorg checks.
    """

    __tablename__ = "chain_cursors"

    stream: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_scanned_block: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    head_block_hash: Mapped[str | None] = mapped_column(String(66))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
