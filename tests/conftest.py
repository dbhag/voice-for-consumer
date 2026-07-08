from __future__ import annotations

import pytest

from engine.extraction_schema import build_extraction_schema
from engine.models import AnswerType, Question, Vertical


@pytest.fixture
def synthetic_vertical() -> Vertical:
    """A second, non-rental vertical used to prove call_loop.py has zero
    vertical-specific branching — the loop must behave identically for any
    Vertical instance.
    """
    question_set = [
        Question(
            id="favorite_color",
            prompt="What's your favorite color?",
            answer_type=AnswerType.STR,
            clarify_prompt="Just roughly, what color would you say?",
        ),
        Question(
            id="score",
            prompt="What's your score out of 10?",
            answer_type=AnswerType.FLOAT,
            clarify_prompt="Approximately what score, even a range is fine?",
        ),
    ]
    return Vertical(
        id="synthetic_test_vertical",
        goal="Test goal.",
        disclosure_script="This is a test disclosure.",
        question_set=question_set,
        extraction_schema=build_extraction_schema("synthetic_test_vertical", question_set),
        result_mode="single",
    )
