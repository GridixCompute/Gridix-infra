"""Application configuration loaded from the environment via Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
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

    secret_key: str = "dev-insecure-secret-change-me"
    # Coordinator key-encryption key (Fernet) for brokering per-job data keys (9.3).
    kek: str = ""
    # Trusted verifier secret standing in for the TEE vendor root of trust (9.5).
    attestation_secret: str = ""

    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "/data/blobs"
    s3_bucket: str = "gridix-blobs"
    s3_endpoint_url: str = ""  # blank → real AWS S3; set for MinIO/localstack
    # Peer-assisted artifact distribution (Session 8.7). Off by default.
    peer_distribution_enabled: bool = False

    # Scheduler / reliability
    lease_seconds: int = Field(default=60, ge=5)
    max_attempts: int = Field(default=3, ge=1)

    # Control channel / presence (Session 7.1)
    poll_hold_seconds: float = Field(default=25.0, ge=0.0)
    poll_tick_seconds: float = Field(default=1.0, gt=0.0)
    connection_timeout_seconds: int = Field(default=30, ge=1)

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
