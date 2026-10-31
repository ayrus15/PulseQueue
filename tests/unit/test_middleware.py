"""Unit tests for the request timeout and max-body-size middleware -
a minimal standalone app, no real DB/Redis needed.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pulsequeue.api.middleware import (
    registerMaxRequestBodySizeMiddleware,
    registerRequestTimeoutMiddleware,
)


def _buildTimeoutTestApp(timeoutSeconds: float, handlerDelaySeconds: float) -> FastAPI:
    app = FastAPI()
    registerRequestTimeoutMiddleware(app, timeoutSeconds)

    @app.get("/slow")
    async def slow() -> dict[str, bool]:
        await asyncio.sleep(handlerDelaySeconds)
        return {"ok": True}

    return app


async def testRequestWithinTheTimeoutSucceeds() -> None:
    app = _buildTimeoutTestApp(timeoutSeconds=1.0, handlerDelaySeconds=0.0)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/slow")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def testRequestExceedingTheTimeoutReturns503() -> None:
    app = _buildTimeoutTestApp(timeoutSeconds=0.05, handlerDelaySeconds=1.0)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/slow")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RequestTimeoutError"


def _buildBodySizeTestApp(maxBodyBytes: int) -> FastAPI:
    app = FastAPI()
    registerMaxRequestBodySizeMiddleware(app, maxBodyBytes)

    @app.post("/echo")
    async def echo() -> dict[str, bool]:
        return {"ok": True}

    return app


async def testRequestWithinTheBodySizeLimitSucceeds() -> None:
    app = _buildBodySizeTestApp(maxBodyBytes=1000)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/echo", content=b"x" * 500)
    assert response.status_code == 200


async def testRequestExceedingTheBodySizeLimitReturns413() -> None:
    app = _buildBodySizeTestApp(maxBodyBytes=1000)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/echo", content=b"x" * 2000)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "RequestEntityTooLargeError"


async def testMissingContentLengthIsNotBlockedByTheBodySizeCheck() -> None:
    """Documents the known limitation noted on
    registerMaxRequestBodySizeMiddleware: a request without a
    Content-Length header (e.g. chunked transfer-encoding) isn't
    covered by this check, only by the real app's full default -
    this isn't a gap this middleware claims to close.
    """
    app = _buildBodySizeTestApp(maxBodyBytes=1000)
    transport = ASGITransport(app=app)

    async def _streamingBody() -> object:
        yield b"x" * 2000

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/echo", content=_streamingBody())
    assert response.status_code == 200
