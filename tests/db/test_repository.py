from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db import repository
from app.db.models import Base
from app.db.session import make_session_factory
from engine.models import (
    CallResult,
    CompletionLevel,
    FieldResult,
    ReachFailure,
    Request,
    TerminalState,
    TranscriptTurn,
)
from tests.conftest import make_test_engine


@pytest.fixture
async def session_factory():
    # Defaults to in-memory SQLite; set TEST_DATABASE_URL to run these same
    # tests against a real Postgres — see docker-compose.yml at the repo
    # root and make_test_engine()'s docstring in tests/conftest.py. SQLite's
    # JSON columns are TEXT with no native JSON type/validation (unlike
    # Postgres' JSONB) — round-tripping works on both because SQLAlchemy's
    # JSON type (de)serializes in Python either way, but that's exactly the
    # kind of divergence worth actually checking against Postgres once,
    # not just noting.
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
        return_fields=["price"],
        context={"car": "2018 Honda Civic"},
        targets=["+15550000001", "+15550000005", "+15550000004"],
    )


async def test_create_job_then_get_job_before_results_reports_queued(
    session_factory, sample_request: Request
) -> None:
    async with session_factory() as session:
        await repository.create_job(session, "job-1", sample_request, "auto_repair", None)

    async with session_factory() as session:
        status_and_result = await repository.get_job(session, "job-1")

    assert status_and_result is not None
    status, error, result = status_and_result
    assert status == "queued"
    assert error is None
    assert result is None


async def test_unknown_job_id_returns_none(session_factory) -> None:
    async with session_factory() as session:
        assert await repository.get_job(session, "does-not-exist") is None


async def test_full_lifecycle_round_trips_every_terminal_state(
    session_factory, sample_request: Request
) -> None:
    now = datetime.now(UTC)
    job_result_results = [
        CallResult(
            target="+15550000001",
            terminal_state=TerminalState.GOT_INFO,
            completion_level=CompletionLevel.FULL,
            fields={"price": FieldResult(value=220.0, source_span="It's $220.")},
            transcript=[TranscriptTurn(turn_id=0, speaker="human", text="It's $220.")],
            call_minutes=2.5,
            started_at=now,
            ended_at=now,
        ),
        CallResult(
            target="+15550000005",
            terminal_state=TerminalState.REFUSED,
            refusal_reason="declined to quote by phone",
            call_minutes=1.0,
            started_at=now,
            ended_at=now,
        ),
        CallResult(
            target="+15550000004",
            terminal_state=TerminalState.COULDNT_REACH,
            reach_failure=ReachFailure.NO_ANSWER,
            call_minutes=0.2,
            started_at=now,
            ended_at=now,
        ),
    ]
    from engine.models import JobResult

    async with session_factory() as session:
        await repository.create_job(session, "job-2", sample_request, "auto_repair", "a@b.com")
        await repository.mark_running(session, "job-2")

    async with session_factory() as session:
        mid_flight = await repository.get_job(session, "job-2")
        assert mid_flight == ("running", None, None)

    async with session_factory() as session:
        await repository.save_job_result(
            session, "job-2", JobResult(request=sample_request, results=job_result_results)
        )

    async with session_factory() as session:
        status_and_result = await repository.get_job(session, "job-2")

    assert status_and_result is not None
    status, error, result = status_and_result
    assert status == "done"
    assert error is None
    assert result is not None
    assert result.request.ask == sample_request.ask
    assert {r.target for r in result.results} == {
        "+15550000001",
        "+15550000005",
        "+15550000004",
    }
    # rank_results ordering: GOT_INFO before REFUSED before COULDNT_REACH.
    assert [r.terminal_state for r in result.results] == [
        TerminalState.GOT_INFO,
        TerminalState.REFUSED,
        TerminalState.COULDNT_REACH,
    ]
    got_info = result.results[0]
    assert got_info.fields["price"].value == 220.0
    assert got_info.fields["price"].source_span == "It's $220."
    assert got_info.transcript[0].text == "It's $220."


async def test_mark_failed_sets_status_and_error_and_stops_looking_like_running(
    session_factory, sample_request: Request
) -> None:
    async with session_factory() as session:
        await repository.create_job(session, "job-3", sample_request, None, None)
        await repository.mark_running(session, "job-3")
        await repository.mark_failed(session, "job-3", "BadRequestError: invalid schema")

    async with session_factory() as session:
        status_and_result = await repository.get_job(session, "job-3")

    assert status_and_result == ("failed", "BadRequestError: invalid schema", None)


async def test_list_jobs_orders_most_recent_first(session_factory, sample_request: Request) -> None:
    async with session_factory() as session:
        await repository.create_job(session, "older", sample_request, None, None)
        await repository.create_job(session, "newer", sample_request, None, None)

    async with session_factory() as session:
        jobs = await repository.list_jobs(session)

    assert [j.id for j in jobs][:2] == ["newer", "older"]
