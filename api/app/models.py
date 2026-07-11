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

    created_at: Mapped[datetime] = _created_at()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Exactly one owner FK is populated (portable XOR: exactly one is non-null).
        CheckConstraint(
            "(developer_id IS NULL) <> (provider_id IS NULL)",
            name="ck_apikey_single_owner",
        ),
    )


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
