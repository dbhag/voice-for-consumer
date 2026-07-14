#!/usr/bin/env python3
"""Create the app's Postgres tables if they don't exist yet.

Companion to scripts/db_setup.sh, which ensures the role/database exist
before this runs. Uses the same `app.config.settings.database_url` the API
and worker connect with, so it stays correct if that URL ever changes.
Safe to re-run: `create_all` no-ops on tables that already exist.
"""

from __future__ import annotations

import asyncio

from app.config import settings
from app.db.models import Base
from app.db.session import make_engine


async def main() -> None:
    engine = make_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("[init_schema] tables ready.")


if __name__ == "__main__":
    asyncio.run(main())
