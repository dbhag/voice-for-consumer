from __future__ import annotations

import asyncio
import time
from datetime import timedelta

from engine.cache import InMemoryCacheStore, normalize_question
from engine.call_loop import run_call
from engine.extraction import ground_field
from engine.models import (
    ClassifyAnswer,
    CompletionLevel,
    ConverseOutcome,
    HoldOutcome,
    MenuOutcome,
    ReachFailure,
    Request,
    TerminalState,
    TranscriptTurn,
)


class StubExtraction:
    async def extract(self, return_fields, transcript):  # type: ignore[no-untyped-def]
        return {f: ground_field(f"value-for-{f}", "source text") for f in return_fields}


class ScriptedSession:
    def __init__(
        self,
        classify: ClassifyAnswer,
        *,
        menu_outcome: MenuOutcome | None = None,
        hold_outcome: HoldOutcome | None = None,
        converse_outcome: ConverseOutcome | None = None,
        hold_delay_seconds: float = 0.0,
    ) -> None:
        self.classify_value = classify
        self.menu_outcome = menu_outcome
        self.hold_outcome = hold_outcome
        self.converse_outcome = converse_outcome
        self.hold_delay_seconds = hold_delay_seconds
        self.callback_requested = False
        self.hung_up = False

    async def classify(self) -> ClassifyAnswer:
        return self.classify_value

    async def navigate_menu(self) -> MenuOutcome:
        assert self.menu_outcome is not None
        return self.menu_outcome

    async def wait_on_hold(self) -> HoldOutcome:
        if self.hold_delay_seconds:
            await asyncio.sleep(self.hold_delay_seconds)
        assert self.hold_outcome is not None
        return self.hold_outcome

    async def request_callback(self) -> None:
        self.callback_requested = True

    async def converse(self, disclosure, primary_question, context):  # type: ignore[no-untyped-def]
        assert self.converse_outcome is not None
        return self.converse_outcome

    async def hangup(self) -> None:
        self.hung_up = True


class ScriptedVoicePlatform:
    def __init__(self, session: ScriptedSession) -> None:
        self.session = session
        self.started = False

    async def start_call(self, phone_number: str) -> ScriptedSession:
        self.started = True
        return self.session


def _converse_outcome(
    text: str, *, refused: bool = False, refusal_reason: str | None = None
) -> ConverseOutcome:
    return ConverseOutcome(
        transcript=[
            TranscriptTurn(turn_id=0, speaker="agent", text="disclosure"),
            TranscriptTurn(turn_id=1, speaker="human", text=text),
        ],
        refused=refused,
        refusal_reason=refusal_reason,
    )


async def test_human_answers_yields_got_info_full(sample_request: Request) -> None:
    session = ScriptedSession(
        ClassifyAnswer.HUMAN, converse_outcome=_converse_outcome("It's $220.")
    )
    platform = ScriptedVoicePlatform(session)
    cache = InMemoryCacheStore()

    result = await run_call(sample_request, "+15550000001", platform, StubExtraction(), cache)

    assert result.terminal_state is TerminalState.GOT_INFO
    assert result.completion_level is CompletionLevel.FULL
    assert session.hung_up is True
    for field in result.fields.values():
        if field.value is not None:
            assert field.source_span is not None


async def test_ivr_hold_human_returns_yields_got_info(sample_request: Request) -> None:
    session = ScriptedSession(
        ClassifyAnswer.IVR,
        menu_outcome=MenuOutcome.HOLD,
        hold_outcome=HoldOutcome.HUMAN_RETURNED,
        converse_outcome=_converse_outcome("It's $220."),
    )
    platform = ScriptedVoicePlatform(session)
    cache = InMemoryCacheStore()

    result = await run_call(sample_request, "+15550000002", platform, StubExtraction(), cache)

    assert result.terminal_state is TerminalState.GOT_INFO


async def test_hold_abandoned_yields_couldnt_reach(sample_request: Request) -> None:
    session = ScriptedSession(ClassifyAnswer.HOLD, hold_outcome=HoldOutcome.ABANDONED)
    platform = ScriptedVoicePlatform(session)
    cache = InMemoryCacheStore()

    result = await run_call(sample_request, "+15550000003", platform, StubExtraction(), cache)

    assert result.terminal_state is TerminalState.COULDNT_REACH
    assert result.reach_failure is ReachFailure.HOLD_ABANDONED


async def test_voicemail_no_answer_busy_yields_couldnt_reach(sample_request: Request) -> None:
    session = ScriptedSession(ClassifyAnswer.VM_NO_ANSWER_BUSY)
    platform = ScriptedVoicePlatform(session)
    cache = InMemoryCacheStore()

    result = await run_call(sample_request, "+15550000004", platform, StubExtraction(), cache)

    assert result.terminal_state is TerminalState.COULDNT_REACH
    assert result.reach_failure is ReachFailure.NO_ANSWER
    assert result.transcript == []


async def test_refusal_yields_refused_with_reason_and_no_extraction(
    sample_request: Request,
) -> None:
    session = ScriptedSession(
        ClassifyAnswer.HUMAN,
        converse_outcome=_converse_outcome(
            "We don't quote by phone.", refused=True, refusal_reason="declined to quote by phone"
        ),
    )
    platform = ScriptedVoicePlatform(session)
    cache = InMemoryCacheStore()

    result = await run_call(sample_request, "+15550000005", platform, StubExtraction(), cache)

    assert result.terminal_state is TerminalState.REFUSED
    assert result.refusal_reason == "declined to quote by phone"
    assert result.fields == {}


async def test_ivr_callback_offered_requests_callback_and_hangs_up(sample_request: Request) -> None:
    session = ScriptedSession(ClassifyAnswer.IVR, menu_outcome=MenuOutcome.CALLBACK_OFFERED)
    platform = ScriptedVoicePlatform(session)
    cache = InMemoryCacheStore()

    result = await run_call(sample_request, "+15550000006", platform, StubExtraction(), cache)

    assert result.terminal_state is TerminalState.COULDNT_REACH
    assert result.reach_failure is ReachFailure.CALLBACK_PENDING
    assert session.callback_requested is True
    assert session.hung_up is True


async def test_fresh_cached_answer_for_every_field_skips_the_dial(sample_request: Request) -> None:
    cache = InMemoryCacheStore()
    key = normalize_question("+15550000001", sample_request.ask)
    for field_name in sample_request.return_fields:
        cached_field = ground_field(f"cached-{field_name}", "cached span")
        await cache.put(key, field_name, cached_field, timedelta(hours=1))

    # No converse_outcome scripted — would raise if the loop actually dialed.
    session = ScriptedSession(ClassifyAnswer.HUMAN)
    platform = ScriptedVoicePlatform(session)

    result = await run_call(sample_request, "+15550000001", platform, StubExtraction(), cache)

    assert result.terminal_state is TerminalState.GOT_INFO
    assert result.from_cache is True
    assert result.call_minutes == 0.0
    assert platform.started is False


async def test_partial_cache_hit_still_dials(sample_request: Request) -> None:
    cache = InMemoryCacheStore()
    key = normalize_question("+15550000001", sample_request.ask)
    cached_field = ground_field("cached", "cached span")
    await cache.put(key, sample_request.return_fields[0], cached_field, timedelta(hours=1))

    session = ScriptedSession(
        ClassifyAnswer.HUMAN, converse_outcome=_converse_outcome("It's $220.")
    )
    platform = ScriptedVoicePlatform(session)

    result = await run_call(sample_request, "+15550000001", platform, StubExtraction(), cache)

    assert result.from_cache is False
    assert platform.started is True


async def test_hold_abandon_threshold_cuts_off_a_stuck_hold(sample_request: Request) -> None:
    """Engine-side guardrail, independent of the platform's own hold
    detection: if wait_on_hold() never returns within the threshold, the
    engine abandons rather than blocking the call (and the job) forever.
    """
    session = ScriptedSession(
        ClassifyAnswer.HOLD, hold_outcome=HoldOutcome.HUMAN_RETURNED, hold_delay_seconds=0.2
    )
    platform = ScriptedVoicePlatform(session)
    cache = InMemoryCacheStore()

    started = time.monotonic()
    result = await run_call(
        sample_request,
        "+15550000001",
        platform,
        StubExtraction(),
        cache,
        hold_abandon_seconds=0.02,
    )
    elapsed = time.monotonic() - started

    assert result.terminal_state is TerminalState.COULDNT_REACH
    assert result.reach_failure is ReachFailure.HOLD_ABANDONED
    # Proves the timeout actually cut the wait short rather than serendipitously
    # finishing first — the scripted hold takes 10x longer than the threshold.
    assert elapsed < 0.1
