"""Request correlation ID middleware (FR4).

Every request gets a correlation ID - the client's own ``X-Correlation-Id``
if it sent one (validated for length/characters, since it ends up in
task rows and log lines), else a generated one - echoed back on the
response so a client can always tie its request to server-side logs,
and to the task created from it (see routes/tasks.py).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

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
