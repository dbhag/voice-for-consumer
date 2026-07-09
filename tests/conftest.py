from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import StaticPool

from app.db.session import make_engine
from engine.models import Request


@pytest.fixture
def sample_request() -> Request:
    return Request(
        ask="quote for front brake pad replacement",
        return_fields=["price", "parts_vs_labor", "earliest_availability"],
        context={"car": "2018 Honda Civic", "mileage": 82000, "symptom": "squealing"},
        targets=["+15550000001"],
    )


def make_test_engine() -> AsyncEngine:
    """DB engine shared by tests/db/test_repository.py, tests/queue/test_tasks.py,
    and tests/api/test_jobs.py. Defaults to an in-memory SQLite (via a single
    shared connection — StaticPool is the standard pattern for that in async
    SQLAlchemy); set TEST_DATABASE_URL to point these same tests at a real
    Postgres instead (e.g. the docker-compose.yml at the repo root) to check
    for the JSON-column and other behavioral divergence SQLite can't catch.
    """
    url = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    if "sqlite" in url:
        return make_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    return make_engine(url)
