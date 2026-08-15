"""The vertical-agnostic per-call state machine (CLAUDE.md's "Call State
Machine" section). CACHE_CHECK before dialing, DIAL -> CLASSIFY_ANSWER ->
NAVIGATE_MENU / WAIT_ON_HOLD / CONVERSE -> a terminal state. There is no
`if <vertical-specific thing>` branch anywhere in this file — every string
the loop speaks comes from `request.ask`/`request.context`, and follow-up
handling is delegated entirely to the bought voice platform's `converse()`.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from engine.cache import CacheStore, normalize_question, ttl_for_field
from engine.models import (
    CallResult,
    ClassifyAnswer,
    CompletionLevel,
    FieldResult,
    HoldOutcome,
    MenuOutcome,
    ReachFailure,
    Request,
    TerminalState,
)
from engine.providers.base import ExtractionProvider, VoiceCallSession, VoicePlatformProvider

DISCLOSURE = (
    "Hi, this is Proxy, an AI assistant calling on behalf of a customer with a "
    "quick question — this call may be recorded."
)


async def _cached_result(
    request: Request, target: str, cache: CacheStore, started_at: datetime
) -> CallResult | None:
    """CACHE_CHECK: only short-circuits the dial if every return_field has a
    fresh cached answer. A partial hit still requires a live call — v1 does
    not fill in the gaps from cache mid-call.
    """
    key = normalize_question(target, request.ask)
    fields: dict[str, FieldResult] = {}
    for field_name in request.return_fields:
        cached = await cache.get(key, field_name)
        if cached is None:
            return None
        fields[field_name] = cached.result
    return CallResult(
        target=target,
        terminal_state=TerminalState.GOT_INFO,
        completion_level=CompletionLevel.FULL,
        fields=fields,
        from_cache=True,
        call_minutes=0.0,
        started_at=started_at,
        ended_at=started_at,
    )


def _call_minutes(started_at: datetime, ended_at: datetime) -> float:
    return (ended_at - started_at).total_seconds() / 60


async def _converse(
    request: Request,
    target: str,
    session: VoiceCallSession,
    extraction: ExtractionProvider,
    cache: CacheStore,
    started_at: datetime,
    hold_seconds: float | None = None,
) -> CallResult:
    outcome = await session.converse(DISCLOSURE, request.ask, request.context)
    await session.hangup()
    ended_at = datetime.now(UTC)
    call_minutes = _call_minutes(started_at, ended_at)

    if outcome.refused:
        return CallResult(
            target=target,
            terminal_state=TerminalState.REFUSED,
            refusal_reason=outcome.refusal_reason,
            transcript=outcome.transcript,
            call_minutes=call_minutes,
            hold_seconds=hold_seconds,
            cost_usd=outcome.cost_usd,
            cost_breakdown_usd=outcome.cost_breakdown_usd,
            started_at=started_at,
            ended_at=ended_at,
        )

    fields = await extraction.extract(request.return_fields, outcome.transcript)
    key = normalize_question(target, request.ask)
    for field_name, result in fields.items():
        if result.value is not None:
            await cache.put(key, field_name, result, ttl_for_field(field_name))

    got_all = all(f in fields and fields[f].value is not None for f in request.return_fields)
    return CallResult(
        target=target,
        terminal_state=TerminalState.GOT_INFO,
        completion_level=CompletionLevel.FULL if got_all else CompletionLevel.PARTIAL,
        fields=fields,
        transcript=outcome.transcript,
        call_minutes=call_minutes,
        hold_seconds=hold_seconds,
        cost_usd=outcome.cost_usd,
        cost_breakdown_usd=outcome.cost_breakdown_usd,
        started_at=started_at,
        ended_at=ended_at,
    )


async def _wait_on_hold(
    session: VoiceCallSession, hold_abandon_seconds: float
) -> tuple[HoldOutcome, float]:
    """Engine-side hold-abandon threshold: a hard cutoff independent of
    whatever the bought voice platform itself does. A platform that never
    returns from hold cannot hang a call past this budget. Also times the
    wait itself — see CallResult.hold_seconds.
    """
    started = time.monotonic()
    try:
        outcome = await asyncio.wait_for(session.wait_on_hold(), timeout=hold_abandon_seconds)
    except TimeoutError:
        outcome = HoldOutcome.ABANDONED
    return outcome, time.monotonic() - started


def _reach_failure(
    target: str, reason: ReachFailure, started_at: datetime, hold_seconds: float | None = None
) -> CallResult:
    ended_at = datetime.now(UTC)
    return CallResult(
        target=target,
        terminal_state=TerminalState.COULDNT_REACH,
        reach_failure=reason,
        call_minutes=_call_minutes(started_at, ended_at),
        hold_seconds=hold_seconds,
        started_at=started_at,
        ended_at=ended_at,
    )


async def run_call(
    request: Request,
    target: str,
    voice_platform: VoicePlatformProvider,
    extraction: ExtractionProvider,
    cache: CacheStore,
    hold_abandon_seconds: float = 180.0,
) -> CallResult:
    started_at = datetime.now(UTC)

    cached = await _cached_result(request, target, cache, started_at)
    if cached is not None:
        return cached

    session = await voice_platform.start_call(request, target)
    classification = await session.classify()

    if classification is ClassifyAnswer.VM_NO_ANSWER_BUSY:
        # No message left on COULDNT_REACH — see CLAUDE.md's non-goals.
        return _reach_failure(target, ReachFailure.NO_ANSWER, started_at)

    if classification is ClassifyAnswer.HOLD:
        hold_outcome, hold_seconds = await _wait_on_hold(session, hold_abandon_seconds)
        if hold_outcome is HoldOutcome.ABANDONED:
            return _reach_failure(
                target, ReachFailure.HOLD_ABANDONED, started_at, hold_seconds=hold_seconds
            )
        return await _converse(
            request, target, session, extraction, cache, started_at, hold_seconds=hold_seconds
        )

    if classification is ClassifyAnswer.IVR:
        menu_outcome = await session.navigate_menu()
        if menu_outcome is MenuOutcome.HUMAN:
            return await _converse(request, target, session, extraction, cache, started_at)
        if menu_outcome is MenuOutcome.HOLD:
            hold_outcome, hold_seconds = await _wait_on_hold(session, hold_abandon_seconds)
            if hold_outcome is HoldOutcome.ABANDONED:
                return _reach_failure(
                    target, ReachFailure.HOLD_ABANDONED, started_at, hold_seconds=hold_seconds
                )
            return await _converse(
                request, target, session, extraction, cache, started_at, hold_seconds=hold_seconds
            )
        # CALLBACK_OFFERED: take it and hang up now to stop the meter — the
        # cost-saver from CLAUDE.md's Cache + Cost Architecture. Resuming on
        # the inbound callback into CONVERSE is P1 (needs inbound routing);
        # v1 stops here with a terminal state instead of blocking on it.
        await session.request_callback()
        await session.hangup()
        return _reach_failure(target, ReachFailure.CALLBACK_PENDING, started_at)

    return await _converse(request, target, session, extraction, cache, started_at)
