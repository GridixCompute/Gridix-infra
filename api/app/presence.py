"""Provider presence — track whether an agent's control channel is live.

Every authenticated agent call bumps ``last_seen``. A provider is *connected* while
``last_seen`` is within ``connection_timeout_seconds``; the first call after a silence (or
ever) opens a new connection window and stamps ``connected_at``. Silence detection latency
is roughly the connection timeout, so keep it a small multiple of the agent's keepalive
interval.
"""

from datetime import UTC, datetime, timedelta

from app.models import Provider


def _as_utc(dt: datetime) -> datetime:
    """Treat tz-naive datetimes (as SQLite returns) as UTC for safe arithmetic."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def is_connected(provider: Provider, now: datetime, timeout_seconds: int) -> bool:
    """Whether the provider's control channel is currently live."""
    if provider.last_seen is None:
        return False
    return _as_utc(provider.last_seen) > now - timedelta(seconds=timeout_seconds)


def mark_seen(provider: Provider, now: datetime, timeout_seconds: int) -> None:
    """Record activity from the provider, opening a new connection window if needed."""
    if not is_connected(provider, now, timeout_seconds):
        provider.connected_at = now
    provider.last_seen = now
