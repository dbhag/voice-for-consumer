from __future__ import annotations

from typing import Any

import fakeredis.aioredis as fakeaioredis
import pytest
from arq.connections import ArqRedis
from arq.worker import Worker

from app.db import repository
from app.db.models import Base
from app.db.session import make_session_factory
from app.notifications import MockNotificationProvider
from app.queue.tasks import run_job_task
from engine.cache import InMemoryCacheStore
from engine.models import Request
from tests.conftest import make_test_engine


@pytest.fixture
async def fake_arq_pool():
    fake = fakeaioredis.FakeRedis()
    pool = ArqRedis(connection_pool=fake.connection_pool)
    yield pool
    await pool.aclose()


@pytest.fixture
async def sqlite_session_factory():
    # Name kept for compatibility with the rest of this file — defaults to
    # SQLite but honors TEST_DATABASE_URL, see tests/conftest.py.
    engine = make_test_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield make_session_factory(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def sample_request() -> Request:
    return Request(
        ask="quote for front brake pad replacement",
        return_fields=["price", "parts_vs_labor", "earliest_availability"],
        context={"car": "2018 Honda Civic", "mileage": 82000, "symptom": "squealing"},
        targets=["+15550000001", "+15550000004"],
    )


async def test_enqueued_job_runs_persists_and_notifies(
    fake_arq_pool: ArqRedis,
    sqlite_session_factory,
    sample_request: Request,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # arq's Worker.main() logs an INFO-command redis summary on startup;
    # fakeredis doesn't implement INFO. Purely cosmetic logging, safe to
    # no-op for the fakeredis-backed test.
    async def _no_op_log_redis_info(*args: Any, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr("arq.worker.log_redis_info", _no_op_log_redis_info)

    notification = MockNotificationProvider()

    async def on_startup(ctx: dict[str, Any]) -> None:
        ctx["session_factory"] = sqlite_session_factory
        ctx["cache"] = InMemoryCacheStore()
        ctx["notification"] = notification

    async def on_shutdown(ctx: dict[str, Any]) -> None:
        pass

    async with sqlite_session_factory() as session:
        await repository.create_job(session, "job-1", sample_request, None, "user@example.com")

    await fake_arq_pool.enqueue_job(
        "run_job_task",
        "job-1",
        sample_request.model_dump(mode="json"),
        "user@example.com",
        _job_id="arq-job-1",
    )

    worker = Worker(
        functions=[run_job_task],
        redis_pool=fake_arq_pool,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        burst=True,
        poll_delay=0,
    )
    await worker.main()
    await worker.close()

    async with sqlite_session_factory() as session:
        status_and_result = await repository.get_job(session, "job-1")

    assert status_and_result is not None
    status, result = status_and_result
    assert status == "done"
    assert result is not None
    assert {r.target for r in result.results} == {"+15550000001", "+15550000004"}

    assert len(notification.sent) == 1
    to, subject, body = notification.sent[0]
    assert to == "user@example.com"
    assert "job-1" in body
