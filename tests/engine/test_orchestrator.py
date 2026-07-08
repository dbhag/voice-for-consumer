from __future__ import annotations

import asyncio

from engine.models import Target, Vertical
from engine.orchestrator import run_job
from engine.providers.base import ProviderBundle
from engine.providers.mock import MockDialogueLLMProvider, MockExtractionProvider


class _SleepySession:
    async def say(self, text: str) -> None:
        return None

    async def listen(self, *, question_id: str, is_clarify: bool = False) -> str:
        await asyncio.sleep(0.02)
        return "answer"


class ConcurrentTelephony:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def start_call(self, target: Target) -> _SleepySession:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        return _SleepySession()

    async def end_call(self, session: _SleepySession) -> None:
        self.active -= 1


async def test_run_job_returns_one_result_per_target_and_runs_concurrently(
    synthetic_vertical: Vertical,
) -> None:
    telephony = ConcurrentTelephony()
    providers = ProviderBundle(
        telephony=telephony,
        dialogue=MockDialogueLLMProvider(),
        extraction=MockExtractionProvider(),
    )
    targets = [Target(id=f"t{i}", name=f"T{i}", phone_number="+1555555000") for i in range(3)]

    results = await run_job(synthetic_vertical, targets, providers)

    assert len(results) == 3
    assert {r.target.id for r in results} == {t.id for t in targets}
    # If run_call+extract ran serially, only one call would ever be "active"
    # at a time — concurrency is the whole point of the orchestrator.
    assert telephony.max_active > 1
