"""Persistence for jobs/call-results — the DB half of the P0 "ranked results
table + per-call transcript cards" requirement. Translates between the
engine's Pydantic domain models (the source of truth for shape) and the
SQLAlchemy rows in `app/db/models.py`.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import CallResultRow, JobRow
from engine.models import CallResult, JobResult, Request
from engine.results import rank_results


async def create_job(
    session: AsyncSession,
    job_id: str,
    request: Request,
    hint_pack_name: str | None,
    notify_email: str | None,
) -> None:
    session.add(
        JobRow(
            id=job_id,
            request=request.model_dump(mode="json"),
            status="queued",
            hint_pack_name=hint_pack_name,
            notify_email=notify_email,
        )
    )
    await session.commit()


async def mark_running(session: AsyncSession, job_id: str) -> None:
    job = await session.get(JobRow, job_id)
    if job is None:
        raise ValueError(f"unknown job_id: {job_id}")
    job.status = "running"
    await session.commit()


async def mark_failed(session: AsyncSession, job_id: str, error: str) -> None:
    job = await session.get(JobRow, job_id)
    if job is None:
        raise ValueError(f"unknown job_id: {job_id}")
    job.status = "failed"
    job.error = error
    await session.commit()


def _call_result_row(job_id: str, result: CallResult) -> CallResultRow:
    return CallResultRow(
        id=str(uuid4()),
        job_id=job_id,
        target=result.target,
        terminal_state=result.terminal_state.value,
        completion_level=result.completion_level.value if result.completion_level else None,
        reach_failure=result.reach_failure.value if result.reach_failure else None,
        refusal_reason=result.refusal_reason,
        fields={name: f.model_dump(mode="json") for name, f in result.fields.items()},
        transcript=[t.model_dump(mode="json") for t in result.transcript],
        from_cache=result.from_cache,
        call_minutes=result.call_minutes,
        cost_usd=result.cost_usd,
        cost_breakdown_usd=result.cost_breakdown_usd,
        started_at=result.started_at,
        ended_at=result.ended_at,
    )


async def save_call_result(session: AsyncSession, job_id: str, result: CallResult) -> None:
    """Persists one call's result as soon as it finishes, independent of the
    rest of the job — see run_job_task's on_call_complete callback in
    app/queue/tasks.py. A crash/timeout after this point loses at most the
    calls still in flight, not every call that already connected and cost
    money.
    """
    session.add(_call_result_row(job_id, result))
    await session.commit()


async def mark_done(session: AsyncSession, job_id: str) -> None:
    job = await session.get(JobRow, job_id)
    if job is None:
        raise ValueError(f"unknown job_id: {job_id}")
    job.status = "done"
    await session.commit()


async def save_job_result(session: AsyncSession, job_id: str, job_result: JobResult) -> None:
    job = await session.get(JobRow, job_id)
    if job is None:
        raise ValueError(f"unknown job_id: {job_id}")
    for result in job_result.results:
        session.add(_call_result_row(job_id, result))
    job.status = "done"
    await session.commit()


def _row_to_call_result(row: CallResultRow) -> CallResult:
    return CallResult.model_validate(
        {
            "target": row.target,
            "terminal_state": row.terminal_state,
            "completion_level": row.completion_level,
            "reach_failure": row.reach_failure,
            "refusal_reason": row.refusal_reason,
            "fields": row.fields,
            "transcript": row.transcript,
            "from_cache": row.from_cache,
            "call_minutes": row.call_minutes,
            "cost_usd": row.cost_usd,
            "cost_breakdown_usd": row.cost_breakdown_usd,
            "started_at": row.started_at,
            "ended_at": row.ended_at,
        }
    )


async def get_job(
    session: AsyncSession, job_id: str
) -> tuple[str, str | None, JobResult | None] | None:
    """Returns (status, error, JobResult | None) — results are None until
    status is "done"; error is None unless status is "failed". Returns None
    outright if job_id doesn't exist (caller 404s).
    """
    stmt = (
        select(JobRow).where(JobRow.id == job_id).options(selectinload(JobRow.call_results))
    )
    job = (await session.execute(stmt)).scalar_one_or_none()
    if job is None:
        return None
    if job.status != "done":
        return job.status, job.error, None
    request = Request.model_validate(job.request)
    results = [_row_to_call_result(row) for row in job.call_results]
    return job.status, None, JobResult(request=request, results=rank_results(results))


async def list_jobs(session: AsyncSession, limit: int = 50) -> list[JobRow]:
    stmt = select(JobRow).order_by(JobRow.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())
