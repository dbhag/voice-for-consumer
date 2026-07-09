"""Async engine/sessionmaker factory backing `app/db/repository.py`.

Production uses `settings.database_url` (Postgres, per CLAUDE.md's Stack
table). Tests/local dev pass an explicit SQLite URL instead — see
`tests/db/test_repository.py` for the in-memory StaticPool setup a single
shared async SQLite connection needs.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings


def make_engine(database_url: str | None = None, **engine_kwargs: object) -> AsyncEngine:
    return create_async_engine(database_url or settings.database_url, **engine_kwargs)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
