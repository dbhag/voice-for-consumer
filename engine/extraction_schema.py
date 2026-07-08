"""Generate a vertical's typed extraction schema from its question set.

This is the mechanism that keeps the engine question-agnostic: a vertical
adds a `Question` to its list and gets a corresponding `ExtractedField[T]`
on the generated model for free. No hand-written extractor class exists
anywhere for any vertical.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from engine.models import AnswerType, ExtractedField, Question

_PRIMITIVE_TYPES: dict[AnswerType, type] = {
    AnswerType.STR: str,
    AnswerType.FLOAT: float,
    AnswerType.INT: int,
    AnswerType.BOOL: bool,
    AnswerType.DATE: date,
}


def _value_type(question: Question) -> Any:
    if question.answer_type is AnswerType.ENUM:
        if not question.enum_values:
            raise ValueError(f"Question {question.id!r} is ENUM but has no enum_values")
        return Literal[tuple(question.enum_values)]
    return _PRIMITIVE_TYPES[question.answer_type]


def build_extraction_schema(vertical_id: str, question_set: list[Question]) -> type[BaseModel]:
    # ExtractedField[_value_type(q)] parametrizes a generic with a runtime
    # value — inherently dynamic, mypy cannot verify it statically.
    fields: dict[str, tuple[Any, Any]] = {}
    for q in question_set:
        field_type = ExtractedField[_value_type(q)]  # type: ignore[misc,valid-type]
        fields[q.id] = (field_type, Field(..., description=q.description or q.prompt))
    model_name = "".join(part.capitalize() for part in vertical_id.split("_")) + "Extraction"
    return create_model(model_name, **fields)  # type: ignore[call-overload,no-any-return]
