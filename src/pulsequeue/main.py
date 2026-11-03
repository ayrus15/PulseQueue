"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from pulsequeue.api.errorHandlers import registerErrorHandlers
from pulsequeue.api.middleware import (
    registerCorrelationIdMiddleware,
    registerMaxRequestBodySizeMiddleware,
    registerRequestMetricsMiddleware,
    registerRequestTimeoutMiddleware,
)
from pulsequeue.api.routes.deadLetters import router as deadLettersRouter
from pulsequeue.api.routes.health import router as healthRouter
from pulsequeue.api.routes.metrics import router as metricsRouter
from pulsequeue.api.routes.tasks import router as tasksRouter
from pulsequeue.core.config import getSettings
from pulsequeue.core.loggingConfig import configureLogging
from pulsequeue.persistence.database import createEngine, createSessionFactory
from pulsequeue.queueing.redisQueue import createRedisClient
from pulsequeue.workers.worker import buildWorker, buildWorkerId

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = getSettings()
    configureLogging(settings.logLevel)
    engine = createEngine(
        settings.databaseUrl,
        connectTimeoutSeconds=settings.dbConnectTimeoutSeconds,
        commandTimeoutSeconds=settings.dbCommandTimeoutSeconds,
        poolTimeoutSeconds=settings.dbPoolTimeoutSeconds,
    )
    app.state.sessionFactory = createSessionFactory(engine)
    app.state.redisClient = createRedisClient(
        settings.redisUrl, connectTimeoutSeconds=settings.redisConnectTimeoutSeconds
    )

    worker = None
    workerTask: asyncio.Task[None] | None = None
    workerEngine = None
    workerRedisClient = None
    if settings.runWorkerInProcess:
        logger.warning(
            "PULSEQUEUE_RUN_WORKER_IN_PROCESS is set - running the worker "
            "inside the API process. This is a deployment-cost concession, "
            "not the documented architecture (see docs/architecture.md) - "
            "prefer `python -m pulsequeue.workers.worker` as its own "
            "process wherever that's an option. See docs/deployment.md.",
        )
        worker, workerEngine, workerRedisClient = buildWorker(
            settings, workerId=f"{buildWorkerId()}-inprocess"
        )
        workerTask = asyncio.create_task(worker.run())

    try:
        yield
    finally:
        if worker is not None and workerTask is not None:
            worker.requestStop()
            await workerTask
        if workerEngine is not None and workerRedisClient is not None:
            await workerRedisClient.aclose()
            await workerEngine.dispose()
        await app.state.redisClient.aclose()
        await engine.dispose()


def createApp() -> FastAPI:
    settings = getSettings()
    app = FastAPI(title="PulseQueue", version="0.1.0", lifespan=lifespan)

    if settings.allowedOriginsList:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowedOriginsList,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    registerErrorHandlers(app)
    registerRequestTimeoutMiddleware(app, settings.apiRequestTimeoutSeconds)
    registerCorrelationIdMiddleware(app)
    registerRequestMetricsMiddleware(app)
    # Registered last so it becomes the outermost middleware (Starlette
    # wraps in reverse registration order) - an oversized request is
    # rejected before any other middleware does work on it.
    registerMaxRequestBodySizeMiddleware(app, settings.maxRequestBodyBytes)
    app.include_router(tasksRouter)
    app.include_router(deadLettersRouter)
    app.include_router(healthRouter)
    app.include_router(metricsRouter)

    uiDirectory = Path(settings.uiDirectory)
    if uiDirectory.is_dir():
        # Mounted under /ui, never at "/" - keeps this purely additive and
        # unambiguous next to /api/v1, /health, /metrics, with no routing
        # precedence to reason about between a static mount and the API
        # routers above.
        app.mount("/ui", StaticFiles(directory=uiDirectory, html=True), name="ui")
    else:
        logger.warning(
            "UI directory not found - dashboard not mounted", extra={"path": str(uiDirectory)}
        )
    return app


app = createApp()
