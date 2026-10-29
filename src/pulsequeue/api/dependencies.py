"""FastAPI dependency wiring: one DB session per request."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def getSession(request: Request) -> AsyncIterator[AsyncSession]:
    sessionFactory = request.app.state.sessionFactory
    async with sessionFactory() as session:
        yield session
