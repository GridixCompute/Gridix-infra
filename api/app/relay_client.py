"""Coordinator → relay client (Session 7.5).

The API and the relay are separate processes. When the coordinator needs to reach a
provider through its tunnel (e.g. to proxy an endpoint request), it calls the relay's
internal bridge over HTTP with the shared secret. This is the one place that knows the
relay's location, so swapping a direct-path transport in later is a local change.
"""

import uuid

import httpx

from app.config import Settings


class RelayUnavailableError(RuntimeError):
    """Raised when the relay can't be reached or the provider isn't connected."""


async def call_provider(
    provider_id: uuid.UUID,
    *,
    method: str,
    payload: dict,
    settings: Settings,
    job_id: str | None = None,
) -> dict:
    """Bridge a request to a provider through the relay; return the provider's reply.

    Raises:
        RelayUnavailableError: If the relay is unreachable or the provider is offline.
    """
    url = f"{settings.relay_internal_url}/relay/providers/{provider_id}/request"
    body = {"job_id": job_id, "method": method, "payload": payload}
    try:
        async with httpx.AsyncClient(timeout=settings.relay_request_timeout + 5) as client:
            resp = await client.post(
                url, headers={"Authorization": f"Bearer {settings.secret_key}"}, json=body
            )
    except httpx.HTTPError as exc:
        raise RelayUnavailableError(f"relay unreachable: {exc}") from exc

    if resp.status_code == 503:
        raise RelayUnavailableError("provider not connected")
    resp.raise_for_status()
    return resp.json()
