"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pulsequeue.api.errorHandlers import registerErrorHandlers
from pulsequeue.api.routes.tasks import router as tasksRouter
from pulsequeue.core.config import getSettings
from pulsequeue.core.loggingConfig import configureLogging
from pulsequeue.persistence.database import createEngine, createSessionFactory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = getSettings()
    configureLogging(settings.logLevel)
    engine = createEngine(settings.databaseUrl)
    app.state.sessionFactory = createSessionFactory(engine)
    try:
        yield
    finally:
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
    app.include_router(tasksRouter)
    return app


app = createApp()
