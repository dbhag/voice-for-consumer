"""arq worker: consumes jobs enqueued by `app/api/routes/jobs.py`, runs the
engine's call-loop fan-out, persists results, and fires the completion
notification. Registered via `WorkerSettings` below — real deploys run
`arq app.queue.tasks.WorkerSettings` against Redis (`settings.redis_url`);
tests/demo construct an `arq.worker.Worker` directly with a fakeredis-backed
`redis_pool`, reusing the same `functions`/`on_startup`/`on_shutdown`.
"""

from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from app.config import settings
from app.db import repository
from app.db.session import make_engine, make_session_factory
from app.notifications import build_notification_provider
from app.providers import build_provider_bundle
from engine.cache import InMemoryCacheStore
from engine.models import Request, TerminalState
from engine.orchestrator import run_job


async def run_job_task(
    ctx: dict[str, Any],
    job_id: str,
    request_json: dict[str, Any],
    notify_email: str | None,
) -> None:
    """arq job args must be JSON-serializable — the Request travels as a
    plain dict, not the Pydantic object itself. `hint_pack_name` isn't a
    param here: it only drives the missing-context check, which already ran
    at submit time in the API route before this job was ever enqueued — it's
    recorded on the JobRow for the record, not re-consulted by the worker.
    """
    request = Request.model_validate(request_json)

    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        await repository.mark_running(session, job_id)

    providers = build_provider_bundle(settings)
    job_result = await run_job(
        request,
        providers,
        ctx["cache"],
        settings.concurrency_cap,
        settings.job_minute_budget,
        settings.hold_abandon_seconds,
    )

    async with session_factory() as session:
        await repository.save_job_result(session, job_id, job_result)

    if notify_email:
        got_info = sum(1 for r in job_result.results if r.terminal_state is TerminalState.GOT_INFO)
        await ctx["notification"].send(
            notify_email,
            "Your Proxy job is ready",
            f"{got_info} of {len(job_result.results)} calls returned info. "
            f"View results: job {job_id}.",
        )


async def _on_startup(ctx: dict[str, Any]) -> None:
    engine = make_engine()
    ctx["engine"] = engine
    ctx["session_factory"] = make_session_factory(engine)
    # One shared cache instance across every job this worker processes, so
    # the cache's cross-job benefit (50 users -> ~1 call) actually applies.
    ctx["cache"] = InMemoryCacheStore()
    ctx["notification"] = build_notification_provider(settings)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [run_job_task]
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
