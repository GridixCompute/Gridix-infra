"""Application configuration loaded from the environment via Pydantic Settings."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the GRIDIX control plane.

    All values are read from environment variables prefixed with ``GRIDIX_`` (or a
    local ``.env`` file). Secrets never have defaults that are safe for production.
    """

    model_config = SettingsConfigDict(
        env_prefix="GRIDIX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "staging", "prod"] = "dev"

    database_url: str = "postgresql+asyncpg://gridix:gridix@localhost:5432/gridix"
    redis_url: str = "redis://localhost:6379/0"

    # Where secrets come from (Session 12.1): env vars, mounted files (Docker/K8s secrets),
    # or a Vault/KMS seam. See app.secret_manager.
    secret_backend: Literal["env", "file", "vault"] = "env"
    secret_dir: str = "/run/secrets"

    secret_key: str = "dev-insecure-secret-change-me"
    # Coordinator key-encryption key (Fernet) for brokering per-job data keys (9.3).
    kek: str = ""
    # Retired KEKs (comma-separated) still accepted during rotation (12.1, zero-downtime).
    kek_previous: str = ""

    @property
    def all_keks(self) -> list[str]:
        """Active KEK first, then any retired ones still valid during rotation."""
        retired = [k.strip() for k in self.kek_previous.split(",") if k.strip()]
        return [self.kek, *retired] if self.kek else retired

    @model_validator(mode="after")
    def _validate_liveness_window(self) -> "Settings":
        """Refuse to boot if the reaper could reclaim a live job between heartbeats.

        connection_timeout must leave room for at least two agent heartbeats; otherwise a
        long-running job's provider ages past the timeout between beats, gets flagged
        unreachable, and its K=1 job is spuriously reassigned to a second provider (which
        then collides on the container name). This bug only surfaces when two independently
        reasonable configs interact, so the code — not a runbook — has to enforce it.
        """
        if self.connection_timeout_seconds <= 2 * self.agent_heartbeat_interval_seconds:
            raise ValueError(
                f"connection_timeout_seconds ({self.connection_timeout_seconds}) must be > "
                f"2 * agent_heartbeat_interval_seconds "
                f"({self.agent_heartbeat_interval_seconds}) so a long job's provider is not "
                "flagged unreachable between heartbeats (see docs/RUNBOOKS.md)."
            )
        return self

    # Trusted verifier secret standing in for the TEE vendor root of trust (9.5).
    attestation_secret: str = ""
    # Lifetime of job-scoped secrets injected into the container (9.6).
    secrets_ttl_seconds: int = Field(default=3600, ge=1)
    # How long a slashed provider has to contest before the slash auto-confirms (10.1).
    dispute_window_seconds: int = Field(default=86_400, ge=1)
    # Health thresholds above which a provider is marked degraded (11.4).
    health_max_gpu_temp_c: float = Field(default=90.0)
    health_max_error_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    # Alerting thresholds (12.7).
    alert_queue_backlog: int = Field(default=100, ge=0)
    alert_min_connected_providers: int = Field(default=1, ge=0)

    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "/data/blobs"
    s3_bucket: str = "gridix-blobs"
    s3_endpoint_url: str = ""  # blank → real AWS S3; set for MinIO/localstack
    # Peer-assisted artifact distribution (Session 8.7). Off by default.
    peer_distribution_enabled: bool = False

    # Scheduler / reliability
    lease_seconds: int = Field(default=60, ge=5)
    max_attempts: int = Field(default=3, ge=1)

    # Port the scheduler worker serves its Prometheus metrics on (12.7 observability).
    scheduler_metrics_port: int = Field(default=9100, ge=1, le=65535)

    # Control channel / presence (Session 7.1)
    poll_hold_seconds: float = Field(default=25.0, ge=0.0)
    poll_tick_seconds: float = Field(default=1.0, gt=0.0)
    connection_timeout_seconds: int = Field(default=30, ge=1)
    # The cadence the coordinator assumes agents heartbeat at. connection_timeout must leave
    # room for at least two heartbeats (see the model validator) so a long-running job's
    # provider isn't flagged unreachable between beats and its job spuriously reassigned.
    agent_heartbeat_interval_seconds: int = Field(default=10, ge=1)

    # Relay / tunnel (Session 7.2-7.3)
    relay_request_timeout: float = Field(default=30.0, gt=0.0)
    # Internal URL the API uses to reach the relay's bridge endpoint (Session 7.5).
    relay_internal_url: str = "http://localhost:8100"
    # Public base the coordinator advertises for endpoint URLs.
    public_base_url: str = "http://localhost:8000"

    # Verification / economics
    canary_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    min_provider_stake: int = Field(default=100, ge=0)
    slash_amount: int = Field(default=50, ge=0)
    high_value_min_reputation: float = Field(default=70.0, ge=0.0)
    protocol_fee_bps: int = Field(default=250, ge=0, le=10_000)
    base_job_price: float = Field(default=1.0, ge=0.0)
    data_price_per_gb: float = Field(default=0.10, ge=0.0)

    # ── On-chain settlement (Session 13) ──────────────────────────────────────────────
    # The off-chain ledger stays the source of truth for per-job accounting; the chain layer
    # only mirrors deposits and pushes *aggregate* settlements. All chain code is behind a
    # ChainClient seam, so with chain_enabled=False (the default) nothing touches an RPC and
    # the whole suite runs hermetically.
    chain_enabled: bool = False
    chain_rpc_url: str = ""
    chain_id: int = Field(default=11155111)  # Sepolia
    escrow_address: str = ""  # GridixEscrow
    staking_address: str = ""  # GridixStaking
    usdc_address: str = ""
    usdc_decimals: int = Field(default=6, ge=0, le=36)
    # Coordinator EOA private key (COORDINATOR_ROLE on both contracts). Read via secret_manager;
    # never a safe default. Used to sign debit/settleBatch/depositSettlement.
    coordinator_private_key: str = ""
    # Confirmations to wait before treating a chain event/receipt as final (reorg guard).
    chain_confirmations: int = Field(default=3, ge=1)
    # Short TTL cache for on-chain balance reads so we don't RPC on every request.
    chain_balance_cache_ttl_seconds: float = Field(default=5.0, ge=0.0)
    # How often the watcher polls for new blocks/events.
    chain_poll_interval_seconds: float = Field(default=5.0, gt=0.0)
    # Settlement trigger: batch when unsettled provider earnings reach this total (USDC, whole
    # units) OR when the scheduled interval elapses — whichever comes first. Threshold fills the
    # batch for gas efficiency; the interval is a floor so small balances never wait forever.
    settlement_threshold_usdc: Decimal = Field(default=Decimal("100"), ge=0)
    settlement_interval_seconds: float = Field(default=3600.0, gt=0.0)
    # How often to reconcile on-chain balances against the off-chain ledger.
    reconcile_interval_seconds: float = Field(default=300.0, gt=0.0)

    # Hardening
    rate_limit_per_minute: int = Field(default=120, ge=1)
    max_request_bytes: int = Field(default=512 * 1024 * 1024, ge=1024)

    @property
    def is_prod(self) -> bool:
        """Whether the process is running in the production environment."""
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
