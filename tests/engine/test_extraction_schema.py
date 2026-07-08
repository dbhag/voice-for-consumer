from __future__ import annotations

import pytest

from engine.extraction_schema import build_extraction_schema
from engine.models import AnswerType, Question


@pytest.mark.parametrize(
    "answer_type,enum_values",
    [
        (AnswerType.STR, None),
        (AnswerType.FLOAT, None),
        (AnswerType.INT, None),
        (AnswerType.BOOL, None),
        (AnswerType.DATE, None),
        (AnswerType.ENUM, ["a", "b"]),
    ],
)
def test_one_extracted_field_per_question(answer_type: AnswerType, enum_values: list[str] | None) -> None:
    question = Question(id="field_a", prompt="Prompt?", answer_type=answer_type, enum_values=enum_values)
    schema = build_extraction_schema("test_vertical", [question])
    assert set(schema.model_fields) == {"field_a"}


def test_enum_without_enum_values_raises() -> None:
    question = Question(id="field_a", prompt="Prompt?", answer_type=AnswerType.ENUM)
    with pytest.raises(ValueError, match="enum_values"):
        build_extraction_schema("test_vertical", [question])


def test_adding_a_question_adds_a_field_with_no_other_code_changes() -> None:
    """Proves the load-bearing rule: adding a Question is the entire diff
    required to add an extracted field — nothing else needs editing."""
    q1 = Question(id="a", prompt="A?", answer_type=AnswerType.STR)
    schema_one = build_extraction_schema("v", [q1])
    assert set(schema_one.model_fields) == {"a"}

    q2 = Question(id="b", prompt="B?", answer_type=AnswerType.FLOAT)
    schema_two = build_extraction_schema("v", [q1, q2])
    assert set(schema_two.model_fields) == {"a", "b"}
