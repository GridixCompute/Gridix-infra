"""Structured error responses — one consistent shape for every failure.

Clients always receive ``{"error": {"type": ..., "message": ..., "detail": ...}}`` so
they can handle failures uniformly. Unexpected exceptions are logged with a trace id and
returned as an opaque 500 (no internal detail leaks to the caller).
"""

import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse


def _error(type_: str, message: str, detail: Any = None, *, status_code: int) -> JSONResponse:
    body: dict[str, Any] = {"error": {"type": type_, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


def install_error_handlers(app: FastAPI) -> None:
    """Register the JSON error handlers on the app."""

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error("http_error", str(exc.detail), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Return only JSON-safe fields. Pydantic's error `ctx` can hold the raw exception
        # object (e.g. from a custom validator raising ValueError), which is not
        # serializable and would otherwise crash the handler — and could leak internals.
        detail = [
            {"type": e.get("type"), "loc": list(e.get("loc", [])), "msg": e.get("msg")}
            for e in exc.errors()
        ]
        return _error(
            "validation_error",
            "Request failed validation.",
            detail=detail,
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def _unhandled_exc(request: Request, exc: Exception) -> JSONResponse:
        trace_id = uuid.uuid4().hex
        logger.opt(exception=exc).error(
            "unhandled error [{}] on {} {}", trace_id, request.method, request.url.path
        )
        return _error(
            "internal_error",
            "An internal error occurred.",
            detail={"trace_id": trace_id},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
