"""Provider seams. Real Pipecat/Twilio/Deepgram/Cartesia implementations plug
into these same Protocols later; this pass only ships mock + LLM-extraction
implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from engine.models import AnswerClassification, Question, Target, TranscriptTurn, Vertical


class ConversationSession(Protocol):
    async def say(self, text: str) -> None: ...

    async def listen(self, *, question_id: str, is_clarify: bool = False) -> str: ...


class TelephonyProvider(Protocol):
    async def start_call(self, target: Target) -> ConversationSession: ...

    async def end_call(self, session: ConversationSession) -> None: ...


class DialogueLLMProvider(Protocol):
    async def classify_answer(
        self, question: Question, answer_text: str, history: list[TranscriptTurn]
    ) -> AnswerClassification: ...


class ExtractionProvider(Protocol):
    async def extract(self, vertical: Vertical, transcript: list[TranscriptTurn]) -> BaseModel: ...


@dataclass
class ProviderBundle:
    telephony: TelephonyProvider
    dialogue: DialogueLLMProvider
    extraction: ExtractionProvider
