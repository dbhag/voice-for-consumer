"""Provider seams.

`VoicePlatformProvider` is the ONE bought voice-infra platform (Bland /
Retell / Vapi) that owns telephony + STT + in-call dialogue LLM + TTS +
turn-taking as a single product — see CLAUDE.md's Stack table. We do not
integrate Twilio/Deepgram/Cartesia/Pipecat directly; that's a self-built
pipeline the spec explicitly rejects.

`PreCallBriefProvider` and `ExtractionProvider` are separate, bought LLM
calls (OpenAI/Anthropic), independent of the voice platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from engine.models import (
    ClassifyAnswer,
    ConverseOutcome,
    FieldResult,
    HoldOutcome,
    MenuOutcome,
    PreCallBrief,
    Request,
    TranscriptTurn,
)


class VoiceCallSession(Protocol):
    """One outbound call, entirely owned by the bought voice platform.

    The platform runs the actual conversation (including dynamic
    follow-up handling under the hard rule) once `converse()` is invoked
    with the disclosure + primary question + context brief — we never
    code a manual turn-by-turn dialogue loop ourselves.

    Not every platform can honor that division cleanly: some (e.g. Retell)
    run the whole call — including whatever would-be converse() content —
    as one atomic operation kicked off at start_call() time, with no
    mid-call checkpoint to defer disclosure/context to. Such adapters may
    find converse()'s arguments moot by the time it's invoked (the call
    already happened) — see engine/providers/retell.py for the concrete
    case and how it's handled without breaking this Protocol's shape.
    """

    async def classify(self) -> ClassifyAnswer: ...

    async def navigate_menu(self) -> MenuOutcome: ...

    async def wait_on_hold(self) -> HoldOutcome: ...

    async def request_callback(self) -> None: ...

    async def converse(
        self, disclosure: str, primary_question: str, context: dict[str, object]
    ) -> ConverseOutcome: ...

    async def hangup(self) -> None: ...


class VoicePlatformProvider(Protocol):
    """`request` is the job's full Request (ask/return_fields/context/
    targets) — real adapters that must front-load context at call-creation
    time (rather than at the later converse() step) need it here; mock/
    simple adapters are free to ignore it.
    """

    async def start_call(self, request: Request, phone_number: str) -> VoiceCallSession: ...


class PreCallBriefProvider(Protocol):
    async def build_brief(
        self, request: Request, hint_pack: dict[str, object] | None
    ) -> PreCallBrief: ...


class ExtractionProvider(Protocol):
    async def extract(
        self, return_fields: list[str], transcript: list[TranscriptTurn]
    ) -> dict[str, FieldResult]: ...


@dataclass
class ProviderBundle:
    voice_platform: VoicePlatformProvider
    pre_call_brief: PreCallBriefProvider
    extraction: ExtractionProvider
