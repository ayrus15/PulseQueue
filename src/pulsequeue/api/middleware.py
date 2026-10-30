"""Request correlation ID middleware (FR4), plus structured request
logging and API request metrics.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

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
