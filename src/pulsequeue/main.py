"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pulsequeue.api.errorHandlers import registerErrorHandlers
from pulsequeue.api.middleware import (
    registerCorrelationIdMiddleware,
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
    try:
        yield
    finally:
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
    app.include_router(tasksRouter)
    app.include_router(deadLettersRouter)
    app.include_router(healthRouter)
    app.include_router(metricsRouter)
    return app


app = createApp()
