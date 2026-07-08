"""Deterministic, offline providers used for local dev / CI / the CLI demo.

No network calls, no API keys required. These implement the same Protocols
(`engine.providers.base`) that real Pipecat/Twilio/Deepgram providers will
implement later.
"""

from __future__ import annotations

from pydantic import BaseModel

from engine.extraction import extract_field_for_question, is_hedge, is_refusal
from engine.models import AnswerClassification, Question, Target, TranscriptTurn, Vertical
from engine.providers.base import ConversationSession

# target_id -> question_id (or "{question_id}__clarify") -> canned human answer.
CANNED_SCRIPTS: dict[str, dict[str, str]] = {
    "t1": {
        "monthly_rent": "It's $1,850 a month.",
        "available_date": "The unit is available August 1st.",
        "pet_policy": "Yes, we allow both cats and dogs, there's a $300 pet deposit.",
        "security_deposit": "The security deposit is $1,850, same as one month's rent.",
        "application_fee": "There's a $50 application fee per applicant.",
        "utilities_included": "Water and trash are included, you'd pay for electric and gas.",
    },
    "t2": {
        "monthly_rent": "It's around $2,000-ish, depends on the unit.",
        "monthly_rent__clarify": "For a one-bedroom it's $2,050 a month.",
        "available_date": "September 15th.",
        "pet_policy": "Cats only, no dogs allowed.",
        "security_deposit": "$2,050.",
        "application_fee": "No application fee.",
        "utilities_included": "None of the utilities are included.",
    },
    "t3": {
        "monthly_rent": "$2,400 a month.",
        "available_date": "Available now, immediate move-in.",
        "pet_policy": "No pets allowed, sorry.",
        "security_deposit": "I'm not able to share that over the phone, you'd need to come in.",
        "application_fee": "$75 application fee.",
        "utilities_included": "All utilities included in the rent.",
    },
}

# Fallback used for any target_id not in CANNED_SCRIPTS, so arbitrary
# user-supplied target files never hard-fail the mock loop.
DEFAULT_SCRIPT: dict[str, str] = {
    "monthly_rent": "It's $1,500 a month.",
    "available_date": "It's available next month.",
    "pet_policy": "Small pets are allowed with a deposit.",
    "security_deposit": "One month's rent.",
    "application_fee": "$40.",
    "utilities_included": "None included.",
}


class MockConversationSession:
    def __init__(self, script: dict[str, str]) -> None:
        self._script = script
        self.said: list[str] = []

    async def say(self, text: str) -> None:
        self.said.append(text)

    async def listen(self, *, question_id: str, is_clarify: bool = False) -> str:
        key = f"{question_id}__clarify" if is_clarify else question_id
        try:
            return self._script[key]
        except KeyError:
            raise KeyError(
                f"MockConversationSession has no canned answer for {key!r}. "
                "Add it to CANNED_SCRIPTS or DEFAULT_SCRIPT."
            ) from None


class MockTelephonyProvider:
    async def start_call(self, target: Target) -> MockConversationSession:
        script = {**DEFAULT_SCRIPT, **CANNED_SCRIPTS.get(target.id, {})}
        return MockConversationSession(script)

    async def end_call(self, session: ConversationSession) -> None:
        return None


class MockDialogueLLMProvider:
    async def classify_answer(
        self, question: Question, answer_text: str, history: list[TranscriptTurn]
    ) -> AnswerClassification:
        if is_refusal(answer_text):
            return AnswerClassification.REFUSED
        if is_hedge(answer_text):
            return AnswerClassification.AMBIGUOUS
        return AnswerClassification.CLEAR


class MockExtractionProvider:
    def __init__(self, threshold: float = 0.7) -> None:
        self.threshold = threshold

    async def extract(self, vertical: Vertical, transcript: list[TranscriptTurn]) -> BaseModel:
        fields = {
            question.id: extract_field_for_question(question, transcript, self.threshold)
            for question in vertical.question_set
        }
        return vertical.extraction_schema(**fields)
