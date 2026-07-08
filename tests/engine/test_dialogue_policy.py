from __future__ import annotations

import pytest

from engine.models import AnswerClassification, AnswerType, Question
from engine.providers.mock import MockDialogueLLMProvider


@pytest.fixture
def question() -> Question:
    return Question(id="q", prompt="P?", answer_type=AnswerType.STR)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("It's $1,850 a month.", AnswerClassification.CLEAR),
        ("Around $2,000-ish, depends on the unit.", AnswerClassification.AMBIGUOUS),
        ("I'm not able to share that over the phone.", AnswerClassification.REFUSED),
        ("No comment.", AnswerClassification.REFUSED),
        ("Roughly $1,500, give or take.", AnswerClassification.AMBIGUOUS),
    ],
)
async def test_classify_answer(question: Question, text: str, expected: AnswerClassification) -> None:
    provider = MockDialogueLLMProvider()
    result = await provider.classify_answer(question, text, [])
    assert result is expected
