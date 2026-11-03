"""Regression test for migrations/env.py's DATABASE_URL handling.

migrations/env.py executes asyncio.run(...) unconditionally at module
import time (it's meant to be exec'd by Alembic's own
ScriptDirectory.run_env(), not imported normally), so this can't
import that module directly - it instead replicates the exact
ConfigParser interaction that line performs, which is the part that
broke.
"""

from __future__ import annotations

import configparser


def testPercentEncodedUrlSurvivesConfigparserRoundTrip() -> None:
    """A real deployment hit this: a Supabase password containing "@"
    and "$" needs percent-encoding (%40, %24) in DATABASE_URL, but
    ConfigParser.set() validates its value for %-interpolation syntax
    immediately - passing a URL with literal "%24"/"%40" straight
    through raised "invalid interpolation syntax" before the migration
    ever got a chance to run. migrations/env.py works around this by
    escaping "%" as ConfigParser's own "%%" literal-percent syntax on
    set, which this test confirms round-trips back to the exact
    original URL on every way env.py subsequently reads it.
    """
    url = (
        "postgresql+asyncpg://postgres.exampleref:"
        "%24ecret%40pass123@aws-0-eu-north-1.pooler.supabase.com:5432/postgres"
    )
    config = configparser.ConfigParser()
    config.add_section("alembic")

    config.set("alembic", "sqlalchemy.url", url.replace("%", "%%"))

    assert config.get("alembic", "sqlalchemy.url") == url
    assert dict(config.items("alembic"))["sqlalchemy.url"] == url
