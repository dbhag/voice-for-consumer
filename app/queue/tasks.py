"""arq worker: consumes jobs enqueued by `app/api/routes/jobs.py`, runs the
engine's call-loop fan-out, persists results, and fires the completion
notification. Registered via `WorkerSettings` below — real deploys run
`arq app.queue.tasks.WorkerSettings` against Redis (`settings.redis_url`);
tests/demo construct an `arq.worker.Worker` directly with a fakeredis-backed
`redis_pool`, reusing the same `functions`/`on_startup`/`on_shutdown`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import arq.worker
from arq.connections import RedisSettings

from app.config import settings
from app.db import repository
from app.db.session import make_engine, make_session_factory
from app.notifications import build_notification_provider
from app.providers import build_provider_bundle
from engine.cache import InMemoryCacheStore
from engine.hint_packs import load_hint_pack
from engine.models import CallResult, Request, TerminalState
from engine.orchestrator import run_job


async def _no_op_log_redis_info(*args: Any, **kwargs: Any) -> None:
    """arq's Worker.main() logs an INFO-command redis summary right after
    startup; fakeredis's TcpFakeServer doesn't implement INFO, so the
    connection dies and the whole worker crashes before on_startup ever
    runs. Purely cosmetic logging — safe to no-op for every backend, not
    just fakeredis-backed dev (see tests/queue/test_tasks.py, which patches
    the same thing for the in-process test worker).
    """


arq.worker.log_redis_info = _no_op_log_redis_info  # type: ignore[attr-defined]


async def run_job_task(
    ctx: dict[str, Any],
    job_id: str,
    request_json: dict[str, Any],
    hint_pack_name: str | None,
    notify_email: str | None,
) -> None:
    """arq job args must be JSON-serializable — the Request travels as a
    plain dict, not the Pydantic object itself. `hint_pack_name` is reloaded
    here (not just consulted at submit time for the missing-context check)
    because a real voice-platform adapter (e.g. Retell) needs the hint pack
    to build its call-creation payload — see
    app/providers.py:build_provider_bundle and engine/providers/retell.py.
    """
    request = Request.model_validate(request_json)
    hint_pack = load_hint_pack(hint_pack_name) if hint_pack_name else None

    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        await repository.mark_running(session, job_id)

    async def _persist_call_result(result: CallResult) -> None:
        async with session_factory() as session:
            await repository.save_call_result(session, job_id, result)

    try:
        providers = build_provider_bundle(settings, hint_pack)
        job_result = await run_job(
            request,
            providers,
            ctx["cache"],
            settings.concurrency_cap,
            settings.job_minute_budget,
            settings.hold_abandon_seconds,
            on_call_complete=_persist_call_result,
        )
    except asyncio.CancelledError:
        # WorkerSettings.job_timeout expiring cancels this coroutine —
        # CancelledError is a BaseException, not an Exception, so it would
        # otherwise skip the block below entirely and propagate straight
        # through arq's own asyncio.wait_for. arq's default retry_jobs=True
        # would then re-enqueue and re-run this whole job from scratch,
        # re-dialing every target a second time — worse than the stuck-at-
        # "running" bug this replaces. Swallowing it here (not re-raising)
        # makes run_job_task return normally from arq's point of view, so
        # the job is reported done-with-a-result, not retried. Each call
        # already placed was persisted as it completed via
        # _persist_call_result above, so only the in-flight call, if any,
        # is lost — not the whole batch.
        async with session_factory() as session:
            await repository.mark_failed(session, job_id, "job exceeded its timeout")
        return
    except Exception as exc:
        # Caught, not re-raised: arq's default retry-on-exception would
        # re-run this whole job — including any calls that already
        # connected and cost real money — for a failure that happened
        # *after* the call (e.g. extraction). A dead job must be visible
        # (status="failed", not stuck at "running" forever), but silently
        # re-dialing a business because our own code broke afterward would
        # be worse. Retrying is a job-submission-time decision for a human,
        # not an automatic one here.
        async with session_factory() as session:
            await repository.mark_failed(session, job_id, f"{type(exc).__name__}: {exc}")
        return

    async with session_factory() as session:
        await repository.mark_done(session, job_id)

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
    # dev.sh's readiness gate greps for this line — it only prints once
    # on_startup has actually run, unlike arq's "Starting worker for..."
    # line, which prints before the redis connection is proven live. print(),
    # not logging, since arq's log config only wires up the "arq" logger —
    # anything logged under our own name would silently vanish.
    print("worker startup complete, ready for jobs", flush=True)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    # Defensive: if on_startup crashed partway through (e.g. before this
    # key was set), don't let shutdown itself raise and mask the real error.
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()


class WorkerSettings:
    functions = [run_job_task]
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # arq's own default (300s) is unrelated to how long a job can legitimately
    # run and was silently shorter than settings.job_minute_budget (30 min
    # default) — a job doing real dialing would get cancelled by arq before
    # its own budget ever kicked in. Derive from job_minute_budget instead of
    # a second hardcoded number that can drift out of sync with it; the fixed
    # buffer covers wall-clock spent on extraction/persistence/notification
    # after the last call finishes, which job_minute_budget doesn't account
    # for (it only tracks call_minutes).
    job_timeout = settings.job_minute_budget * 60 + 60
