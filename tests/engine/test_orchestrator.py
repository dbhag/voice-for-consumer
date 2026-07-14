from __future__ import annotations

import asyncio

from engine.cache import InMemoryCacheStore
from engine.models import (
    ClassifyAnswer,
    ConverseOutcome,
    HoldOutcome,
    MenuOutcome,
    ReachFailure,
    Request,
    TerminalState,
    TranscriptTurn,
)
from engine.orchestrator import run_job
from engine.providers.base import ProviderBundle
from engine.providers.mock import MockExtractionProvider, MockPreCallBriefProvider


class _SleepySession:
    def __init__(self, platform: ConcurrentVoicePlatform) -> None:
        self._platform = platform

    async def classify(self) -> ClassifyAnswer:
        return ClassifyAnswer.HUMAN

    async def navigate_menu(self) -> MenuOutcome:
        raise NotImplementedError("never reached — classify() always returns HUMAN")

    async def wait_on_hold(self) -> HoldOutcome:
        raise NotImplementedError("never reached — classify() always returns HUMAN")

    async def request_callback(self) -> None:
        raise NotImplementedError("never reached — classify() always returns HUMAN")

    async def converse(
        self, disclosure: str, primary_question: str, context: dict[str, object]
    ) -> ConverseOutcome:
        await asyncio.sleep(0.02)
        return ConverseOutcome(
            transcript=[
                TranscriptTurn(turn_id=0, speaker="agent", text=disclosure),
                TranscriptTurn(turn_id=1, speaker="human", text="It's $100."),
            ]
        )

    async def hangup(self) -> None:
        self._platform.active -= 1


class ConcurrentVoicePlatform:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def start_call(self, request: Request, phone_number: str) -> _SleepySession:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        return _SleepySession(self)


async def test_run_job_returns_one_result_per_target(sample_request: Request) -> None:
    request = sample_request.model_copy(update={"targets": [f"+1555000{i:04d}" for i in range(3)]})
    platform = ConcurrentVoicePlatform()
    providers = ProviderBundle(
        voice_platform=platform,
        pre_call_brief=MockPreCallBriefProvider(),
        extraction=MockExtractionProvider(),
    )
    cache = InMemoryCacheStore()

    job_result = await run_job(request, providers, cache, concurrency_cap=5)

    assert len(job_result.results) == 3
    assert {r.target for r in job_result.results} == set(request.targets)
    # If calls ran serially, only one would ever be "active" at once —
    # concurrency is the whole point of the orchestrator.
    assert platform.max_active > 1


async def test_concurrency_cap_bounds_simultaneous_calls(sample_request: Request) -> None:
    request = sample_request.model_copy(update={"targets": [f"+1555000{i:04d}" for i in range(6)]})
    platform = ConcurrentVoicePlatform()
    providers = ProviderBundle(
        voice_platform=platform,
        pre_call_brief=MockPreCallBriefProvider(),
        extraction=MockExtractionProvider(),
    )
    cache = InMemoryCacheStore()

    await run_job(request, providers, cache, concurrency_cap=2)

    assert platform.max_active <= 2


class _BudgetSession:
    """Each call takes a small, real, fixed slice of wall-clock time so
    call_minutes is deterministically nonzero and comparable across calls.
    """

    def __init__(self, platform: _BudgetPlatform) -> None:
        self._platform = platform

    async def classify(self) -> ClassifyAnswer:
        return ClassifyAnswer.HUMAN

    async def navigate_menu(self) -> MenuOutcome:
        raise NotImplementedError("never reached — classify() always returns HUMAN")

    async def wait_on_hold(self) -> HoldOutcome:
        raise NotImplementedError("never reached — classify() always returns HUMAN")

    async def request_callback(self) -> None:
        raise NotImplementedError("never reached — classify() always returns HUMAN")

    async def converse(
        self, disclosure: str, primary_question: str, context: dict[str, object]
    ) -> ConverseOutcome:
        await asyncio.sleep(0.05)
        return ConverseOutcome(
            transcript=[
                TranscriptTurn(turn_id=0, speaker="agent", text=disclosure),
                TranscriptTurn(turn_id=1, speaker="human", text="It's $100."),
            ]
        )

    async def hangup(self) -> None:
        pass


class _BudgetPlatform:
    def __init__(self) -> None:
        self.start_call_count = 0

    async def start_call(self, request: Request, phone_number: str) -> _BudgetSession:
        self.start_call_count += 1
        return _BudgetSession(self)


async def test_job_minute_budget_skips_remaining_targets_once_exhausted(
    sample_request: Request,
) -> None:
    """Cost guardrail: a job-level minute budget stops further dialing once
    spent, without dropping the remaining targets — they still come back as
    first-class (skipped) results, not silently missing.
    """
    request = sample_request.model_copy(update={"targets": [f"+1555000{i:04d}" for i in range(3)]})
    platform = _BudgetPlatform()
    providers = ProviderBundle(
        voice_platform=platform,
        pre_call_brief=MockPreCallBriefProvider(),
        extraction=MockExtractionProvider(),
    )
    cache = InMemoryCacheStore()

    # concurrency_cap=1 forces serial execution so the budget check for call N
    # always sees the accounted cost of calls 1..N-1 — no concurrent overshoot
    # window to reason about. Budget is set to fit exactly one ~0.05s call
    # (~0.0008 min) and comfortably reject a second.
    job_result = await run_job(
        request, providers, cache, concurrency_cap=1, job_minute_budget=0.0005
    )

    assert len(job_result.results) == 3
    assert platform.start_call_count == 1

    dialed = [r for r in job_result.results if r.call_minutes > 0]
    skipped = [r for r in job_result.results if r.call_minutes == 0]
    assert len(dialed) == 1
    assert len(skipped) == 2
    for result in skipped:
        assert result.terminal_state is TerminalState.COULDNT_REACH
        assert result.reach_failure is ReachFailure.BUDGET_EXCEEDED
