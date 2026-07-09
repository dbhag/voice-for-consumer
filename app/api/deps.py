"""FastAPI dependencies for the DB session and the arq enqueue pool. Both
live on `app.state`, set up in `app/main.py`'s startup hook; tests override
these via `app.dependency_overrides` to point at an in-memory SQLite
session factory and a fakeredis-backed arq pool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from arq.connections import ArqRedis
from fastapi import Request as FastAPIRequest
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: FastAPIRequest) -> AsyncIterator[AsyncSession]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_arq_pool(request: FastAPIRequest) -> ArqRedis:
    return request.app.state.arq_pool  # type: ignore[no-any-return]
