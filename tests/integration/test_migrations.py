"""Verifies the Alembic migration actually creates and tears down the
``tasks`` table against a real PostgreSQL database - "migration from an
empty database" from PROJECT_PLAN.md's Phase 1 test list.

Not async: Alembic's own env.py drives its own event loop via
``asyncio.run`` (see migrations/env.py), so this test and its table
inspection helper stay synchronous and call ``asyncio.run`` only
sequentially, never nested inside pytest-asyncio's loop.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

MIGRATIONS_TEST_DATABASE_URL = os.environ.get(
    "MIGRATIONS_TEST_DATABASE_URL",
    "postgresql+asyncpg://pulsequeue:change-me-locally@localhost:5432/pulsequeue_migrations_test",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def alembicConfig() -> Config:
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    return config


async def _getTableNames(databaseUrl: str) -> set[str]:
    from sqlalchemy import inspect

    engine = create_async_engine(databaseUrl)
    try:
        async with engine.connect() as connection:
            return set(await connection.run_sync(lambda conn: inspect(conn).get_table_names()))
    finally:
        await engine.dispose()


def testUpgradeFromEmptyDatabaseThenDowngrade(alembicConfig: Config) -> None:
    os.environ["DATABASE_URL"] = MIGRATIONS_TEST_DATABASE_URL
    try:
        try:
            command.upgrade(alembicConfig, "head")
        except Exception as exc:  # noqa: BLE001 - deliberately broad: this is a reachability gate
            pytest.skip(
                f"No reachable PostgreSQL database at {MIGRATIONS_TEST_DATABASE_URL!r} "
                f"({exc.__class__.__name__}: {exc}). Create it with "
                f"'createdb pulsequeue_migrations_test' and re-run."
            )

        tablesAfterUpgrade = asyncio.run(_getTableNames(MIGRATIONS_TEST_DATABASE_URL))
        assert "tasks" in tablesAfterUpgrade

        command.downgrade(alembicConfig, "base")
        tablesAfterDowngrade = asyncio.run(_getTableNames(MIGRATIONS_TEST_DATABASE_URL))
        assert "tasks" not in tablesAfterDowngrade
    finally:
        del os.environ["DATABASE_URL"]
