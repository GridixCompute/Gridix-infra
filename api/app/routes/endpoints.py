"""Endpoint-style jobs (Session 7.5).

A job that declares ``exposed_port`` runs a long-lived HTTP server inside its container.
The coordinator mints a routed, capability-token'd URL; calls to it are forwarded through
the relay tunnel to the container's port on the (NAT'd) provider, and the reply is
streamed back. The developer never needs the provider's address.

``GET /jobs/{id}/endpoint`` (developer auth) returns the URL + token. The gateway
``/{method} /endpoints/{job_id}/{path}`` is authed by that token (not the API key), so it
can be handed to any client.
"""

import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.deps import DeveloperDep, SessionDep, SettingsDep
from app.models import Job, JobStatus
from app.relay_client import RelayUnavailableError, call_provider
from app.schemas import EndpointInfo
from app.security import endpoint_token, verify_endpoint_token

router = APIRouter(tags=["endpoints"])

_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]


@router.get("/jobs/{job_id}/endpoint", response_model=EndpointInfo)
async def get_endpoint(
    job_id: uuid.UUID, developer: DeveloperDep, session: SessionDep, settings: SettingsDep
) -> EndpointInfo:
    """Return the routed URL + capability token for an endpoint job the caller owns."""
    job = await session.get(Job, job_id)
    if job is None or job.developer_id != developer.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    if job.exposed_port is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Job does not expose a port."
        )
    token = endpoint_token(str(job.id), settings.secret_key)
    url = f"{settings.public_base_url.rstrip('/')}/endpoints/{job.id}/"
    return EndpointInfo(url=url, token=token, port=job.exposed_port)


# Transparent reverse-proxy to a job's exposed HTTP port. It is a passthrough,
# not part of the typed JSON API contract, so it stays out of the OpenAPI schema
# (one function serving many methods otherwise emits a duplicate operationId,
# which FastAPI warns about and breaks generated clients).
@router.api_route("/endpoints/{job_id}/{path:path}", methods=_METHODS, include_in_schema=False)
async def endpoint_gateway(
    job_id: uuid.UUID,
    path: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    """Forward an authenticated request to the job's container port through the tunnel."""
    token = request.headers.get("x-endpoint-token") or request.query_params.get("token")
    if not token or not verify_endpoint_token(str(job_id), token, settings.secret_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid endpoint token."
        )

    job = await session.get(Job, job_id)
    if job is None or job.exposed_port is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found.")
    if job.status is not JobStatus.running or job.assigned_provider_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Endpoint is not live.")

    body = await request.body()
    payload = {
        "kind": "endpoint",
        "port": job.exposed_port,
        "path": "/" + path,
        "query": str(request.url.query),
        "method": request.method,
        "body": body.decode("utf-8", errors="replace"),
    }
    try:
        reply = await call_provider(
            job.assigned_provider_id,
            method=request.method,
            payload=payload,
            settings=settings,
            job_id=str(job.id),
        )
    except RelayUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"provider unreachable: {exc}"
        ) from exc

    inner = reply.get("payload") or {}
    return Response(
        content=inner.get("body", ""),
        status_code=int(reply.get("status", 200)),
        media_type=inner.get("content_type", "application/octet-stream"),
    )
