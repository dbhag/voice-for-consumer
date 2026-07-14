from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from click.testing import CliRunner

from app.cli import cli
from app.db import repository
from app.db.models import Base
from app.db.session import make_engine, make_session_factory
from engine.models import (
    CallResult,
    CompletionLevel,
    FieldResult,
    JobResult,
    ReachFailure,
    Request,
    TerminalState,
    TranscriptTurn,
)


def _init_schema(db_url: str) -> None:
    async def _init() -> None:
        engine = make_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_init())


def _seed_completed_job(db_url: str, job_id: str) -> None:
    async def _seed() -> None:
        engine = make_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)

        request = Request(
            ask="quote for front brake pad replacement",
            return_fields=["price"],
            context={"car": "2018 Honda Civic"},
            targets=["+15550000001", "+15550000004"],
        )
        results = [
            CallResult(
                target="+15550000001",
                terminal_state=TerminalState.GOT_INFO,
                completion_level=CompletionLevel.FULL,
                fields={"price": FieldResult(value=220.0, source_span="It's $220.")},
                transcript=[TranscriptTurn(turn_id=0, speaker="human", text="It's $220.")],
                call_minutes=1.5,
                started_at=datetime.now(UTC),
            ),
            CallResult(
                target="+15550000004",
                terminal_state=TerminalState.COULDNT_REACH,
                reach_failure=ReachFailure.NO_ANSWER,
                call_minutes=0.1,
                started_at=datetime.now(UTC),
            ),
        ]

        async with session_factory() as session:
            await repository.create_job(session, job_id, request, None, None)
            await repository.save_job_result(
                session, job_id, JobResult(request=request, results=results)
            )
        await engine.dispose()

    asyncio.run(_seed())


def test_report_renders_markdown_table_for_a_completed_job(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'report_test.db'}"
    _seed_completed_job(db_url, "job-report-1")

    runner = CliRunner()
    result = runner.invoke(cli, ["report", "job-report-1", "--database-url", db_url])

    assert result.exit_code == 0, result.output
    assert "job-report-1" in result.output
    assert "+15550000001" in result.output
    assert "got_info (full)" in result.output
    assert "price" in result.output
    assert "+15550000004" in result.output
    assert "no_answer" in result.output
    # No LLM configured in the test environment (no .env, defaults to "fake").
    assert "not audited" in result.output


def test_report_unknown_job_id_fails_loudly(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}"
    _init_schema(db_url)

    runner = CliRunner()
    result = runner.invoke(cli, ["report", "does-not-exist", "--database-url", db_url])

    assert result.exit_code != 0


def test_report_job_not_done_yet_fails_loudly(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'queued.db'}"
    _init_schema(db_url)

    async def _seed_queued() -> None:
        engine = make_engine(db_url)
        session_factory = make_session_factory(engine)
        request = Request(
            ask="quote for front brake pad replacement",
            return_fields=["price"],
            targets=["+15550000001"],
        )
        async with session_factory() as session:
            await repository.create_job(session, "job-queued", request, None, None)
        await engine.dispose()

    asyncio.run(_seed_queued())

    runner = CliRunner()
    result = runner.invoke(cli, ["report", "job-queued", "--database-url", db_url])

    assert result.exit_code != 0
    assert "not done yet" in result.output
