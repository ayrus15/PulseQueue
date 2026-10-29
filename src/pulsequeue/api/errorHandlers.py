"""Maps every exception that can escape a route handler to a consistent,
sanitized JSON error response. This is the only place that does that
mapping - route handlers just let domain errors propagate.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from pulsequeue.domain.errors import (
    IdempotencyConflictError,
    InvalidStateTransitionError,
    PulseQueueError,
    TaskNotFoundError,
    UnauthorizedError,
    UnsupportedTaskTypeError,
)
from pulsequeue.domain.errors import (
    ValidationError as DomainValidationError,
)

logger = logging.getLogger(__name__)

_DOMAIN_ERROR_STATUS: dict[type[PulseQueueError], int] = {
    DomainValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    UnsupportedTaskTypeError: status.HTTP_400_BAD_REQUEST,
    TaskNotFoundError: status.HTTP_404_NOT_FOUND,
    InvalidStateTransitionError: status.HTTP_409_CONFLICT,
    IdempotencyConflictError: status.HTTP_409_CONFLICT,
    UnauthorizedError: status.HTTP_401_UNAUTHORIZED,
}


def _errorBody(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def registerErrorHandlers(app: FastAPI) -> None:
    @app.exception_handler(PulseQueueError)
    async def handlePulseQueueError(request: Request, exc: PulseQueueError) -> JSONResponse:
        statusCode = _DOMAIN_ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
        return JSONResponse(
            status_code=statusCode,
            content=_errorBody(type(exc).__name__, str(exc)),
        )

    @app.exception_handler(RequestValidationError)
    async def handleRequestValidationError(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_errorBody("RequestValidationError", str(exc.errors())),
        )

    @app.exception_handler(PydanticValidationError)
    async def handlePydanticValidationError(
        request: Request, exc: PydanticValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_errorBody("ValidationError", str(exc.errors())),
        )

    @app.exception_handler(Exception)
    async def handleUnexpectedError(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled exception while processing %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_errorBody("InternalServerError", "An unexpected error occurred."),
        )
