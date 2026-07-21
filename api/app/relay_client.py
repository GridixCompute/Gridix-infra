"""Coordinator → relay client (Session 7.5).

The API and the relay are separate processes. When the coordinator needs to reach a
provider through its tunnel (e.g. to proxy an endpoint request), it calls the relay's
internal bridge over HTTP with the shared secret. This is the one place that knows the
relay's location, so swapping a direct-path transport in later is a local change.
"""

import json
import uuid
from collections.abc import AsyncIterator

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
                url, headers={"Authorization": f"Bearer {settings.relay_key}"}, json=body
            )
    except httpx.HTTPError as exc:
        raise RelayUnavailableError(f"relay unreachable: {exc}") from exc

    if resp.status_code == 503:
        raise RelayUnavailableError("provider not connected")
    resp.raise_for_status()
    return resp.json()


async def stream_provider(
    provider_id: uuid.UUID,
    *,
    method: str,
    payload: dict,
    settings: Settings,
    job_id: str | None = None,
) -> AsyncIterator[dict]:
    """Bridge a streamed request through the relay, yielding each NDJSON frame as it lands.

    The timeout is per-read, not per-request: a generation may run far longer than any
    single unary call, so a total deadline would cut off long but healthy streams. What must
    not happen is waiting forever on a node that has gone quiet, and a read timeout bounds
    exactly that.

    Abandoning this generator closes the HTTP response, which the relay sees as its consumer
    disconnecting — that is the signal that ultimately reaches the node as ``cancel``. So the
    caller stopping early is not merely allowed, it is the mechanism.

    Raises:
        RelayUnavailableError: If the relay is unreachable or the provider is offline.
    """
    url = f"{settings.relay_internal_url}/relay/providers/{provider_id}/stream"
    body = {"job_id": job_id, "method": method, "payload": payload}
    timeout = httpx.Timeout(
        connect=10.0, read=settings.relay_request_timeout, write=10.0, pool=10.0
    )
    try:
        async with (
            httpx.AsyncClient(timeout=timeout) as client,
            client.stream(
                "POST",
                url,
                headers={"Authorization": f"Bearer {settings.relay_key}"},
                json=body,
            ) as resp,
        ):
            if resp.status_code == 503:
                raise RelayUnavailableError("provider not connected")
            if resp.status_code >= 400:
                # A streaming response has no body until it is read, and
                # raise_for_status on an unread one raises ResponseNotRead instead of
                # the error we actually want to report.
                await resp.aread()
                resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    frame = json.loads(line)
                except ValueError:
                    # The relay writes these lines, so this is a bug rather than
                    # hostile input — but a stream must not die on one bad line.
                    continue
                if isinstance(frame, dict):
                    yield frame
    except httpx.HTTPStatusError:
        raise
    except httpx.HTTPError as exc:
        raise RelayUnavailableError(f"relay unreachable: {exc}") from exc
