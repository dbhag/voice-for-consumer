"""Adversarial phrase-table coverage for the rental vertical's disclosure
script and the mock dialogue classifier.

KNOWN GAP: this is NOT the full adversarial suite CLAUDE.md ultimately
requires. It exercises `MockDialogueLLMProvider`'s deterministic keyword
heuristic, not a real LLM — there is no real `DialogueLLMProvider`
implementation yet (see engine/providers/). True robustness against
hostile/rushed humans, actual STT interruption handling, and IVR-tree
navigation can only be honestly tested once that lands. The cases below
that fall through to CLEAR document the heuristic's current ceiling rather
than pretending it handles them.
"""

from __future__ import annotations

import pytest

from engine.models import AnswerClassification, AnswerType, Question
from engine.prompts import load_prompt
from engine.providers.mock import MockDialogueLLMProvider


def test_disclosure_discloses_ai_and_who_its_calling_for() -> None:
    text = load_prompt("rental", "disclosure").lower()
    assert "ai" in text
    assert "on behalf of" in text
    assert "i am a human" not in text
    assert "i'm a real person" not in text


@pytest.fixture
def question() -> Question:
    return Question(id="q", prompt="P?", answer_type=AnswerType.STR)


ADVERSARIAL_CASES = [
    ("around 2k-ish, depends", AnswerClassification.AMBIGUOUS),
    ("I'm not able to share that over the phone", AnswerClassification.REFUSED),
    ("no comment", AnswerClassification.REFUSED),
    # Hostile, interruption-fragment, and IVR-menu text all currently fall
    # through to CLEAR under the keyword heuristic — a real dialogue LLM is
    # required to classify these correctly. Documented gap, see module docstring.
    ("why do you need to know that", AnswerClassification.CLEAR),
    ("wait, hold on—", AnswerClassification.CLEAR),
    ("press 1 for leasing, press 2 for maintenance", AnswerClassification.CLEAR),
    ("", AnswerClassification.CLEAR),
]


@pytest.mark.parametrize("text,expected", ADVERSARIAL_CASES)
async def test_adversarial_phrases_classify_as_expected(
    question: Question, text: str, expected: AnswerClassification
) -> None:
    provider = MockDialogueLLMProvider()
    result = await provider.classify_answer(question, text, [])
    assert result is expected
