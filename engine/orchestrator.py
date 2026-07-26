"""Async fan-out over a job's targets, bounded by a concurrency cap — P0 per
CLAUDE.md ("N > cap targets -> no more than cap calls run concurrently").
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from engine.cache import CacheStore
from engine.call_loop import run_call
from engine.models import CallResult, JobResult, ReachFailure, Request, TerminalState
from engine.providers.base import ProviderBundle

DEFAULT_CONCURRENCY_CAP = 5
DEFAULT_HOLD_ABANDON_SECONDS = 180.0


def _budget_exceeded_result(target: str) -> CallResult:
    now = datetime.now(UTC)
    return CallResult(
        target=target,
        terminal_state=TerminalState.COULDNT_REACH,
        reach_failure=ReachFailure.BUDGET_EXCEEDED,
        call_minutes=0.0,
        started_at=now,
        ended_at=now,
    )


async def run_job(
    request: Request,
    providers: ProviderBundle,
    cache: CacheStore,
    concurrency_cap: int = DEFAULT_CONCURRENCY_CAP,
    job_minute_budget: float | None = None,
    hold_abandon_seconds: float = DEFAULT_HOLD_ABANDON_SECONDS,
    on_call_complete: Callable[[CallResult], Awaitable[None]] | None = None,
) -> JobResult:
    semaphore = asyncio.Semaphore(concurrency_cap)
    # Plain float, not a lock-guarded counter: the increment below runs after
    # each call's single `await` resolves, so there's no interleaved
    # read-then-write race within one task. Some concurrent overshoot past
    # budget is possible (bounded by concurrency_cap) — an accepted tradeoff
    # for a soft per-job budget, not a hard per-call limiter.
    minutes_spent = 0.0

    async def _run_one(target: str) -> CallResult:
        nonlocal minutes_spent
        async with semaphore:
            if job_minute_budget is not None and minutes_spent >= job_minute_budget:
                result = _budget_exceeded_result(target)
            else:
                result = await run_call(
                    request,
                    target,
                    providers.voice_platform,
                    providers.extraction,
                    cache,
                    hold_abandon_seconds,
                )
                minutes_spent += result.call_minutes
            # Fired per-call, not just at job end, so a caller (e.g. the arq
            # worker) can persist results incrementally — a mid-job crash or
            # timeout then loses at most the calls still in flight, not every
            # call that already connected and cost money.
            if on_call_complete is not None:
                await on_call_complete(result)
            return result

    results = list(await asyncio.gather(*(_run_one(t) for t in request.targets)))
    return JobResult(request=request, results=results)
