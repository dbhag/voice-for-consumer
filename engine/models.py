"""Vertical-agnostic domain models for the generic outbound-calling engine.

No vertical logic lives here. A vertical's only footprint anywhere in this
codebase is a "hint pack" (plain data, see hint_packs/) consumed by the
pre-call brief's completeness check — never a branch in this module or
anywhere in engine/.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Boundaries(BaseModel):
    read_only: bool = True
    do_not_share: list[str] = Field(default_factory=list)


def _normalize_field_name(raw: str) -> str:
    """Turns plain-language field names ("earliest availability") into the
    snake_case keys extraction/results use ("earliest_availability") —
    mechanical/deterministic, not an LLM call, so a caller (the dashboard)
    never has to know or type the machine-readable form.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
    return slug or raw


class Request(BaseModel):
    """The three-part input: ask + context bundle + targets, plus boundaries.

    Generic by construction — no vertical field exists here. Per-vertical
    "hint packs" enrich the pre-call brief's completeness check as a
    data-driven bolt-on; they never shape this schema.
    """

    ask: str
    return_fields: list[str]
    context: dict[str, Any] = Field(default_factory=dict)
    boundaries: Boundaries = Field(default_factory=Boundaries)
    targets: list[str]

    @field_validator("return_fields")
    @classmethod
    def _normalize_return_fields(cls, value: list[str]) -> list[str]:
        return [_normalize_field_name(v) for v in value]


class TranscriptTurn(BaseModel):
    turn_id: int
    speaker: Literal["agent", "human", "ivr"]
    text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FieldResult(BaseModel):
    """One returned field's value. The hard rule lives here structurally:
    a caller can construct `value=None` freely, but never `value=<something>`
    without `source_span` — see `engine.extraction.ground_field`.
    """

    value: Any | None
    source_span: str | None
    confidence: float | None = None  # P1 soft signal, not the P0 grounding gate
    reason: str | None = None


class TerminalState(StrEnum):
    GOT_INFO = "got_info"
    COULDNT_REACH = "couldnt_reach"
    REFUSED = "refused"


class CompletionLevel(StrEnum):
    FULL = "full"
    PARTIAL = "partial"


class ReachFailure(StrEnum):
    VOICEMAIL = "voicemail"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    HOLD_ABANDONED = "hold_abandoned"
    # IVR offered "press N, we'll call you back" and we took it (cost-saver,
    # stops the meter). Full inbound-callback resumption into CONVERSE is
    # P1 — v1 records this terminal state instead of blocking on it.
    CALLBACK_PENDING = "callback_pending"
    # Job-level per-job minute budget already spent before this target's
    # turn came up — skipped without dialing, a cost guardrail, not a crash.
    BUDGET_EXCEEDED = "budget_exceeded"


class ClassifyAnswer(StrEnum):
    HUMAN = "human"
    IVR = "ivr"
    HOLD = "hold"
    VM_NO_ANSWER_BUSY = "vm_no_answer_busy"


class MenuOutcome(StrEnum):
    HOLD = "hold"
    HUMAN = "human"
    CALLBACK_OFFERED = "callback_offered"


class HoldOutcome(StrEnum):
    HUMAN_RETURNED = "human_returned"
    ABANDONED = "abandoned"


class ConverseOutcome(BaseModel):
    transcript: list[TranscriptTurn]
    refused: bool = False
    refusal_reason: str | None = None
    # Real per-call cost, when the voice platform reports one (e.g. Retell's
    # call_analysis.call_cost). None — not 0.0 — when the platform has no
    # cost signal; never a fabricated estimate.
    cost_usd: float | None = None


class CallResult(BaseModel):
    target: str
    terminal_state: TerminalState
    completion_level: CompletionLevel | None = None  # set only for GOT_INFO
    reach_failure: ReachFailure | None = None  # set only for COULDNT_REACH
    refusal_reason: str | None = None  # set only for REFUSED
    fields: dict[str, FieldResult] = Field(default_factory=dict)
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    from_cache: bool = False
    call_minutes: float = 0.0
    # Wall-clock time spent in WAIT_ON_HOLD. None when the call never reached
    # hold — which, for the Retell adapter, is always (classify() never
    # surfaces HOLD; see engine/providers/retell.py's module docstring).
    hold_seconds: float | None = None
    # See ConverseOutcome.cost_usd — passed through unchanged from whatever
    # converse() reported; None (not 0.0) when no calls reached CONVERSE
    # (e.g. COULDNT_REACH) or the platform has no cost signal.
    cost_usd: float | None = None
    started_at: datetime
    ended_at: datetime | None = None


class MissingContext(BaseModel):
    field: str
    prompt: str


class PreCallBrief(BaseModel):
    primary_question: str
    return_fields: list[str]
    likely_follow_ups: list[str]
    missing_context: list[MissingContext] = Field(default_factory=list)
    # Context keys the brief judged to hold a non-answer ("not sure",
    # "n/a"...) rather than a stated fact. Must never reach the call — the
    # hard rule stops the agent from *inventing* a fact, but a context
    # bundle that already contains a non-fact needs stopping earlier than
    # that. A key here that's also in missing_context is a non-answer the
    # user could plausibly still resolve (re-prompted); a key here alone
    # means the brief judged it genuinely unresolvable and nothing more to
    # ask — see app/api/routes/jobs.py, which drops these before a job is
    # ever created.
    dropped_context_keys: list[str] = Field(default_factory=list)


class JobResult(BaseModel):
    request: Request
    results: list[CallResult]
