"""Async fan-out: one call per target, run concurrently."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from engine.call_loop import run_call
from engine.models import CallResult, Target, Vertical
from engine.providers.base import ProviderBundle


async def run_job(
    vertical: Vertical,
    targets: list[Target],
    providers: ProviderBundle,
) -> list[CallResult]:
    async def _run_one(target: Target) -> CallResult:
        started_at = datetime.now(UTC)
        turns, outcome = await run_call(vertical, target, providers.telephony, providers.dialogue)
        extracted = await providers.extraction.extract(vertical, turns)
        return CallResult(
            target=target,
            outcome=outcome,
            transcript=turns,
            extracted=extracted,
            started_at=started_at,
            ended_at=datetime.now(UTC),
        )

    return list(await asyncio.gather(*(_run_one(t) for t in targets)))
