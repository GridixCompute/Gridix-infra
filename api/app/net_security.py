"""Transport-security validation — pentest wave 1: TLS everywhere.

Every network hop that carries a secret (the relay bearer, endpoint/capability tokens,
DB/Redis credentials) or user data must be encrypted in production. This module fails a
non-dev boot **closed** the moment a configured URL would push such traffic over cleartext
(``http``/``ws``/plain ``redis``/no-SSL Postgres) to a host that isn't loopback.

Loopback is the one exemption: traffic to ``localhost`` / ``127.0.0.1`` / ``::1`` / a unix
socket never crosses a wire an attacker can tap, so requiring TLS there buys nothing and
would only break single-box and CI deployments. Everything else in ``env in {staging, prod}``
must be TLS or the process refuses to start — there is no "warn and continue", because a
silent cleartext hop is exactly the leak the audit flagged (H1/H2/H9/M5/M7).
"""

from urllib.parse import parse_qs, urlsplit

from app.config import Settings

# TLS-affirmative values for a Postgres ``ssl`` / ``sslmode`` query parameter. ``prefer`` and
# ``allow`` are deliberately excluded: they permit a silent downgrade to cleartext, so they are
# NOT accepted as "TLS is on".
_TLS_SSLMODES = {"require", "required", "verify-ca", "verify-full", "true", "1", "on", "yes"}

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}


class TlsConfigurationError(RuntimeError):
    """Raised when a non-dev deployment would send secrets/data over cleartext."""


def _host_of(url: str) -> str:
    """Return the lowercased hostname of ``url`` (empty when it has none)."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        # A URL we can't even parse is not something we can prove is safe → treat as
        # non-loopback so the TLS check below rejects it (fail closed).
        return "unparseable.invalid"


def is_loopback(host: str) -> bool:
    """True when ``host`` is a loopback address whose traffic never hits the wire.

    Note ``0.0.0.0`` is treated as loopback here only as a *host in a target URL* nobody
    should really dial; the meaningful case is localhost/127.0.0.1/::1 for single-box dev.
    """
    return host in _LOOPBACK_HOSTS or host.endswith(".localhost")


def _is_tls_url(url: str, secure_schemes: set[str]) -> bool:
    """True when ``url``'s scheme is one of ``secure_schemes`` (e.g. https/wss/rediss)."""
    return (urlsplit(url).scheme or "").lower() in secure_schemes


def _pg_has_tls(url: str) -> bool:
    """True when a Postgres URL requests SSL via ``ssl`` or ``sslmode`` (affirmatively)."""
    try:
        query = urlsplit(url).query
    except ValueError:
        return False
    params = parse_qs(query)
    for key in ("ssl", "sslmode"):
        values = params.get(key)
        if values and values[0].strip().lower() in _TLS_SSLMODES:
            return True
    return False


def _check(problems: list[str], name: str, url: str, *, secure: bool) -> None:
    """Append a problem for ``name`` unless ``url`` is empty, loopback, or already secure."""
    if not url:
        return
    if is_loopback(_host_of(url)):
        return
    if not secure:
        problems.append(
            f"{name}={url!r} is cleartext to a non-loopback host; use an encrypted transport"
        )


def validate_tls_config(settings: Settings) -> None:
    """Fail fast if a staging/prod deployment would send secrets or data over cleartext.

    Covers every remote hop the coordinator initiates or advertises:

    * ``relay_internal_url`` — carries the relay bearer secret (H9) → must be ``https``.
    * ``public_base_url`` — advertised endpoint URLs carry capability tokens (H2) → ``https``.
    * ``database_url`` / ``redis_url`` — carry DB/cache credentials (M5) → TLS required.
    * ``vault_addr`` — reads every managed secret → ``https``.
    * ``chain_rpc_url`` — only when chain is enabled → ``https``/``wss``.

    Dev is exempt (the whole hermetic suite runs on http/localhost); loopback hosts are exempt
    in every env. All problems are reported at once so a misconfig is fixed in one pass.
    """
    if settings.env == "dev":
        return
    problems: list[str] = []

    _check(
        problems,
        "GRIDIX_RELAY_INTERNAL_URL",
        settings.relay_internal_url,
        secure=_is_tls_url(settings.relay_internal_url, {"https"}),
    )
    _check(
        problems,
        "GRIDIX_PUBLIC_BASE_URL",
        settings.public_base_url,
        secure=_is_tls_url(settings.public_base_url, {"https"}),
    )
    _check(
        problems,
        "GRIDIX_DATABASE_URL",
        settings.database_url,
        secure=_pg_has_tls(settings.database_url),
    )
    _check(
        problems,
        "GRIDIX_REDIS_URL",
        settings.redis_url,
        secure=_is_tls_url(settings.redis_url, {"rediss"}),
    )
    if settings.vault_addr:
        _check(
            problems,
            "GRIDIX_VAULT_ADDR",
            settings.vault_addr,
            secure=_is_tls_url(settings.vault_addr, {"https"}),
        )
    if settings.chain_enabled and settings.chain_rpc_url:
        _check(
            problems,
            "GRIDIX_CHAIN_RPC_URL",
            settings.chain_rpc_url,
            secure=_is_tls_url(settings.chain_rpc_url, {"https", "wss"}),
        )

    if problems:
        raise TlsConfigurationError(
            f"refusing to start in env={settings.env!r} with cleartext transport: "
            + "; ".join(problems)
        )
