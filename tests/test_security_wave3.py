"""Security wave 3 — hardening: CORS allowlist (never '*'), endpoint token out of
the query string, and a bounded relay WebSocket frame.
"""

from unittest.mock import AsyncMock, patch

import pytest
from app.config import Settings, get_settings
from app.main import create_app
from app.relay import _MAX_FRAME_BYTES, _receive_json_bounded
from app.security import endpoint_token
from httpx import ASGITransport, AsyncClient


# ── CORS: only allowlisted origins, wildcard never honoured ──────────────────────
def test_cors_origins_list_strips_wildcard_and_blanks() -> None:
    s = Settings(cors_allow_origins="https://app.example, *, , https://admin.example")
    assert s.cors_origins_list == ["https://app.example", "https://admin.example"]
    assert Settings(cors_allow_origins="*").cors_origins_list == []


async def test_cors_echoes_only_the_allowlisted_origin() -> None:
    cfg = get_settings().model_copy(update={"cors_allow_origins": "https://good.example"})
    with patch("app.main.get_settings", return_value=cfg):
        app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.get("/health", headers={"Origin": "https://good.example"})
        assert ok.headers.get("access-control-allow-origin") == "https://good.example"

        evil = await client.get("/health", headers={"Origin": "https://evil.example"})
        acao = evil.headers.get("access-control-allow-origin")
        assert acao != "*"
        assert acao != "https://evil.example"


# ── Endpoint token must NOT be accepted from the query string ─────────────────────
async def test_endpoint_token_in_query_is_rejected(client: AsyncClient) -> None:
    """A query-param token leaks into logs; the gateway now requires the header."""
    job_id = "11111111-1111-1111-1111-111111111111"
    token = endpoint_token(job_id, get_settings().endpoint_signing_key)

    # Valid token, but presented in the QUERY string → rejected (no header).
    q = await client.get(f"/endpoints/{job_id}/some/path?token={token}")
    assert q.status_code == 401

    # Same token in the header authenticates (then 404 because the job doesn't exist) —
    # proving the header path still works and only the query vector was removed.
    h = await client.get(f"/endpoints/{job_id}/some/path", headers={"x-endpoint-token": token})
    assert h.status_code == 404


# ── Relay frame size cap (anti-DoS) ───────────────────────────────────────────────
async def test_relay_frame_over_cap_is_rejected() -> None:
    oversized = '{"x":"' + "A" * (_MAX_FRAME_BYTES + 10) + '"}'
    ws = AsyncMock()
    ws.receive_text.return_value = oversized
    with pytest.raises(ValueError, match="size limit"):
        await _receive_json_bounded(ws)


async def test_relay_frame_within_cap_parses() -> None:
    ws = AsyncMock()
    ws.receive_text.return_value = '{"type": "auth", "key": "grdx_x"}'
    assert await _receive_json_bounded(ws) == {"type": "auth", "key": "grdx_x"}
