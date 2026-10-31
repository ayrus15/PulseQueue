"""Request correlation ID middleware (FR4), plus structured request
logging, API request metrics, and a request timeout.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from pulsequeue.observability.metrics import apiRequestDurationSeconds, apiRequestsTotal

logger = logging.getLogger(__name__)

CORRELATION_ID_HEADER = "X-Correlation-Id"
_VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def registerCorrelationIdMiddleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def addCorrelationId(
        request: Request, callNext: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        clientProvided = request.headers.get(CORRELATION_ID_HEADER)
        correlationId = (
            clientProvided
            if clientProvided and _VALID_CORRELATION_ID.match(clientProvided)
            else str(uuid.uuid4())
        )
        request.state.correlationId = correlationId
        response = await callNext(request)
        response.headers[CORRELATION_ID_HEADER] = correlationId
        return response


def registerRequestTimeoutMiddleware(app: FastAPI, timeoutSeconds: float) -> None:
    """Bounds total request handling time (FR9's "set sensible timeouts") -
    without this, one slow or stuck handler can occupy a request slot
    forever instead of failing fast with a clear error.
    """

    @app.middleware("http")
    async def enforceRequestTimeout(
        request: Request, callNext: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await asyncio.wait_for(callNext(request), timeout=timeoutSeconds)
        except TimeoutError:
            logger.warning(
                "Request exceeded the timeout",
                extra={"method": request.method, "path": request.url.path},
            )
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": {
                        "code": "RequestTimeoutError",
                        "message": f"Request exceeded {timeoutSeconds}s",
                    }
                },
            )


def registerMaxRequestBodySizeMiddleware(app: FastAPI, maxBodyBytes: int) -> None:
    """Rejects a request whose declared body size exceeds ``maxBodyBytes``
    with 413, before any of it is read (FR9's "set sensible size limits") -
    without this, a client could send an arbitrarily large body and have
    it fully buffered into memory before any field-level validation (e.g.
    a payload string's ``max_length``) ever gets a chance to reject it.

    Checked against the declared ``Content-Length`` header only - a
    request that omits it (e.g. chunked transfer-encoding) is not covered
    here; this is a basic guard for the common case, not a substitute for
    an operator-side reverse proxy body-size limit in a real deployment.
    """

    @app.middleware("http")
    async def enforceMaxRequestBodySize(
        request: Request, callNext: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        contentLength = request.headers.get("content-length")
        if contentLength is not None:
            try:
                declaredSize = int(contentLength)
            except ValueError:
                declaredSize = None
            if declaredSize is not None and declaredSize > maxBodyBytes:
                logger.warning(
                    "Rejected request exceeding max body size",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "declaredSize": declaredSize,
                    },
                )
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={
                        "error": {
                            "code": "RequestEntityTooLargeError",
                            "message": f"Request body exceeds {maxBodyBytes} bytes",
                        }
                    },
                )
        return await callNext(request)


def registerRequestMetricsMiddleware(app: FastAPI) -> None:
    """Records pulsequeue_api_requests_total / _duration_seconds (labeled
    by the route's *template*, e.g. ``/api/v1/tasks/{taskId}`` - never
    the raw path, which would blow up cardinality with one series per
    task ID) and logs one structured line per request.
    """

    @app.middleware("http")
    async def logAndMeasureRequest(
        request: Request, callNext: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        startedAt = time.perf_counter()
        response = await callNext(request)
        durationSeconds = time.perf_counter() - startedAt

        route = request.scope.get("route")
        pathTemplate = getattr(route, "path", request.url.path)

        apiRequestsTotal.labels(
            method=request.method, path=pathTemplate, status_code=str(response.status_code)
        ).inc()
        apiRequestDurationSeconds.labels(method=request.method, path=pathTemplate).observe(
            durationSeconds
        )
        logger.info(
            "Handled request",
            extra={
                "method": request.method,
                "path": pathTemplate,
                "status_code": response.status_code,
                "duration_ms": round(durationSeconds * 1000, 2),
                "correlation_id": getattr(request.state, "correlationId", None),
            },
        )
        return response
