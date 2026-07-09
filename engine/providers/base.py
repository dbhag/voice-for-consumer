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
    async def start_call(self, phone_number: str) -> VoiceCallSession: ...


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
