"""Fixtures for tests that need a real PostgreSQL database.

These tests are skipped - not failed - when no database is reachable, so
a clean checkout without Docker/Postgres still reports an honest result
(see README.md's "Current limitations"). To run them for real:

    createdb pulsequeue_test   # or: psql -c "CREATE DATABASE pulsequeue_test;"
    set TEST_DATABASE_URL=postgresql+asyncpg://pulsequeue:change-me-locally@localhost:5432/pulsequeue_test
    pytest tests/integration

Schema is created directly from the ORM metadata (``Base.metadata.create_all``)
rather than by running Alembic migrations, which keeps each test run
independent of migration history. Alembic's own migration (upgrade from
empty to head) is exercised separately - see
tests/integration/test_migrations.py.

Each async engine is created and disposed within the single event loop
that runs it (asyncpg binds connections to the loop that opened them;
reusing a pool across pytest-asyncio's per-test loops corrupts asyncio's
internals on Windows). Schema create/drop therefore happens once per
session through a plain synchronous fixture driving its own throwaway
event loop via ``asyncio.run``, kept entirely separate from the
function-scoped ``engine`` fixture each test actually uses.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from pulsequeue.persistence.database import createEngine, createSessionFactory
from pulsequeue.persistence.models import Base

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://pulsequeue:change-me-locally@localhost:5432/pulsequeue_test"
)


def testDatabaseUrl() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


async def _createAllTables(databaseUrl: str) -> None:
    engine = createEngine(databaseUrl)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def _dropAllTables(databaseUrl: str) -> None:
    engine = createEngine(databaseUrl)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def schemaReady() -> Iterator[None]:
    databaseUrl = testDatabaseUrl()
    try:
        asyncio.run(_createAllTables(databaseUrl))
    except (OperationalError, OSError) as exc:
        pytest.skip(
            f"No reachable PostgreSQL test database at {databaseUrl!r} "
            f"({exc.__class__.__name__}). Install PostgreSQL, create the database, and set "
            "TEST_DATABASE_URL - see this file's module docstring for the exact commands."
        )
    yield
    asyncio.run(_dropAllTables(databaseUrl))


@pytest_asyncio.fixture
async def engine(schemaReady: None) -> AsyncIterator[AsyncEngine]:
    anEngine = createEngine(testDatabaseUrl())
    yield anEngine
    async with anEngine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())
    await anEngine.dispose()


@pytest_asyncio.fixture
async def dbSession(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    sessionFactory = createSessionFactory(engine)
    async with sessionFactory() as session:
        yield session
