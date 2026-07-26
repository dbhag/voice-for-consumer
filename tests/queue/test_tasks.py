from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import fakeredis.aioredis as fakeaioredis
import pytest
from arq.connections import ArqRedis
from arq.worker import Worker
from sqlalchemy import select

from app.db import repository
from app.db.models import Base, CallResultRow
from app.db.session import make_session_factory
from app.notifications import MockNotificationProvider
from app.queue.tasks import run_job_task
from engine.cache import InMemoryCacheStore
from engine.models import CallResult, CompletionLevel, Request, TerminalState
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
        None,
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
    status, error, result = status_and_result
    assert status == "done"
    assert error is None
    assert result is not None
    assert {r.target for r in result.results} == {"+15550000001", "+15550000004"}

    assert len(notification.sent) == 1
    to, subject, body = notification.sent[0]
    assert to == "user@example.com"
    assert "job-1" in body


async def test_job_that_raises_mid_run_is_marked_failed_not_stuck_running(
    fake_arq_pool: ArqRedis,
    sqlite_session_factory,
    sample_request: Request,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reproduces the real incident this test exists for: a call can
    # complete fine and still leave the job dead if something after it
    # (extraction, in the real 2026-07-14 failure) raises. Before the
    # "failed" status existed, this left the row stuck at "running" forever
    # — see app/db/repository.py's mark_failed / app/queue/tasks.py's
    # try/except around run_job.
    async def _no_op_log_redis_info(*args: Any, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr("arq.worker.log_redis_info", _no_op_log_redis_info)

    async def _raising_run_job(*args: Any, **kwargs: Any) -> None:
        raise ValueError("boom")

    monkeypatch.setattr("app.queue.tasks.run_job", _raising_run_job)

    notification = MockNotificationProvider()

    async def on_startup(ctx: dict[str, Any]) -> None:
        ctx["session_factory"] = sqlite_session_factory
        ctx["cache"] = InMemoryCacheStore()
        ctx["notification"] = notification

    async def on_shutdown(ctx: dict[str, Any]) -> None:
        pass

    async with sqlite_session_factory() as session:
        await repository.create_job(session, "job-2", sample_request, None, "user@example.com")

    await fake_arq_pool.enqueue_job(
        "run_job_task",
        "job-2",
        sample_request.model_dump(mode="json"),
        None,
        "user@example.com",
        _job_id="arq-job-2",
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
        status_and_result = await repository.get_job(session, "job-2")

    assert status_and_result is not None
    status, error, result = status_and_result
    assert status == "failed"
    assert error == "ValueError: boom"
    assert result is None
    # No completion notification for a job that never completed.
    assert len(notification.sent) == 0


async def test_job_that_times_out_is_marked_failed_not_retried_and_keeps_partial_results(
    fake_arq_pool: ArqRedis,
    sqlite_session_factory,
    sample_request: Request,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduces the timeout bug: arq's own job_timeout (previously a fixed
    300s, unrelated to job_minute_budget) cancels run_job_task by raising
    CancelledError into it — a BaseException, invisible to `except
    Exception`. Two things must hold: (1) the job ends up "failed", not
    stuck at "running" or silently retried (arq's retry_jobs=True default
    would otherwise re-dial every target from scratch on an uncaught
    CancelledError — see app/queue/tasks.py's except-clause comment), and
    (2) whatever call already completed and was persisted via
    on_call_complete survives the timeout, even though the job as a whole
    didn't finish.
    """
    async def _no_op_log_redis_info(*args: Any, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr("arq.worker.log_redis_info", _no_op_log_redis_info)

    async def _slow_run_job(
        request: Request,
        providers: Any,
        cache: Any,
        concurrency_cap: int,
        job_minute_budget: float | None,
        hold_abandon_seconds: float,
        on_call_complete: Any = None,
    ) -> None:
        # Mimics one call finishing (and getting persisted) before the rest
        # of the job hangs past the worker's timeout.
        if on_call_complete is not None:
            now = datetime.now(UTC)
            await on_call_complete(
                CallResult(
                    target=request.targets[0],
                    terminal_state=TerminalState.GOT_INFO,
                    completion_level=CompletionLevel.FULL,
                    call_minutes=0.1,
                    started_at=now,
                    ended_at=now,
                )
            )
        await asyncio.sleep(10)

    monkeypatch.setattr("app.queue.tasks.run_job", _slow_run_job)

    notification = MockNotificationProvider()

    async def on_startup(ctx: dict[str, Any]) -> None:
        ctx["session_factory"] = sqlite_session_factory
        ctx["cache"] = InMemoryCacheStore()
        ctx["notification"] = notification

    async def on_shutdown(ctx: dict[str, Any]) -> None:
        pass

    async with sqlite_session_factory() as session:
        await repository.create_job(session, "job-3", sample_request, None, "user@example.com")

    await fake_arq_pool.enqueue_job(
        "run_job_task",
        "job-3",
        sample_request.model_dump(mode="json"),
        None,
        "user@example.com",
        _job_id="arq-job-3",
    )

    worker = Worker(
        functions=[run_job_task],
        redis_pool=fake_arq_pool,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        burst=True,
        poll_delay=0,
        job_timeout=0.3,
    )
    await worker.main()
    await worker.close()

    async with sqlite_session_factory() as session:
        status_and_result = await repository.get_job(session, "job-3")
        persisted = (
            await session.execute(select(CallResultRow).where(CallResultRow.job_id == "job-3"))
        ).scalars().all()

    assert status_and_result is not None
    status, error, result = status_and_result
    assert status == "failed"
    assert error == "job exceeded its timeout"
    assert result is None
    # The one call that finished before the timeout was persisted
    # incrementally and survives even though the job itself failed.
    assert [row.target for row in persisted] == [sample_request.targets[0]]
    # Not retried: a retry would have re-run _slow_run_job and, since arq's
    # burst mode drains the queue until empty, would show up as a second
    # attempt — this asserts there's exactly the one row from the one call.
    assert len(notification.sent) == 0
