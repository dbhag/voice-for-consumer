"""Vertical-agnostic domain models.

This module must never import anything vertical-specific (no rental,
no subscription-cancellation, etc). A `Vertical` is data; the engine
only ever sees `Vertical` instances, never vertical ids in branches.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, SerializeAsAny


class AnswerType(StrEnum):
    STR = "str"
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    DATE = "date"
    ENUM = "enum"


class Question(BaseModel):
    id: str
    prompt: str
    answer_type: AnswerType
    required: bool = True
    enum_values: list[str] | None = None
    clarify_prompt: str | None = None
    description: str | None = None


class ExtractedField[T](BaseModel):
    value: T | None
    confidence: float = Field(ge=0.0, le=1.0)
    source_span: str | None
    needs_human_review: bool
    reason: str | None = None


class Vertical(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    id: str
    goal: str
    disclosure_script: str
    question_set: list[Question]
    extraction_schema: type[BaseModel]
    result_mode: Literal["compare", "single"]


class TranscriptTurn(BaseModel):
    turn_id: int
    speaker: Literal["agent", "human", "ivr"]
    text: str
    question_id: str | None = None
    is_clarify: bool = False
    timestamp: datetime | None = None


class Target(BaseModel):
    id: str
    name: str
    phone_number: str
    metadata: dict[str, str] = Field(default_factory=dict)


class Job(BaseModel):
    id: str
    vertical_id: str
    targets: list[Target]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CallOutcome(StrEnum):
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    VOICEMAIL = "voicemail"
    FAILED = "failed"


class AnswerClassification(StrEnum):
    CLEAR = "clear"
    AMBIGUOUS = "ambiguous"
    REFUSED = "refused"


class CallResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    target: Target
    outcome: CallOutcome
    transcript: list[TranscriptTurn]
    extracted: SerializeAsAny[BaseModel]
    started_at: datetime
    ended_at: datetime | None = None


class ComparisonResult(BaseModel):
    vertical_id: str
    results: list[CallResult]


class SingleResult(BaseModel):
    vertical_id: str
    result: CallResult
