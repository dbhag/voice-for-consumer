from __future__ import annotations

from engine.extraction import extract_field_for_question
from engine.models import AnswerType, Question, TranscriptTurn


def _human_turn(turn_id: int, text: str, question_id: str, is_clarify: bool = False) -> TranscriptTurn:
    return TranscriptTurn(
        turn_id=turn_id, speaker="human", text=text, question_id=question_id, is_clarify=is_clarify
    )


def test_refusal_is_not_flagged_for_review() -> None:
    question = Question(id="deposit", prompt="P?", answer_type=AnswerType.FLOAT)
    turns = [_human_turn(1, "I'm not able to share that over the phone.", "deposit")]
    field = extract_field_for_question(question, turns, threshold=0.7)
    assert field.value is None
    assert field.reason == "declined"
    assert field.needs_human_review is False


def test_clean_answer_extracts_typed_value_with_verbatim_source_span() -> None:
    question = Question(id="rent", prompt="P?", answer_type=AnswerType.FLOAT)
    turns = [_human_turn(1, "It's $1,850 a month.", "rent")]
    field = extract_field_for_question(question, turns, threshold=0.7)
    assert field.value == 1850.0
    assert field.source_span == "It's $1,850 a month."
    assert field.needs_human_review is False


def test_unparseable_answer_flags_but_keeps_source_span() -> None:
    question = Question(id="rent", prompt="P?", answer_type=AnswerType.FLOAT)
    turns = [_human_turn(1, "It varies a lot, hard to say.", "rent")]
    field = extract_field_for_question(question, turns, threshold=0.7)
    assert field.value is None
    assert field.source_span is not None
    assert field.needs_human_review is True


def test_no_answer_captured_yields_none_with_no_source_span() -> None:
    question = Question(id="rent", prompt="P?", answer_type=AnswerType.FLOAT)
    field = extract_field_for_question(question, [], threshold=0.7)
    assert field.value is None
    assert field.source_span is None
    assert field.needs_human_review is True


def test_hedged_primary_then_clarify_resolves_confidently() -> None:
    question = Question(id="rent", prompt="P?", answer_type=AnswerType.FLOAT)
    turns = [
        _human_turn(1, "Around $2,000-ish, depends on the unit.", "rent"),
        _human_turn(2, "For a one-bedroom it's $2,050 a month.", "rent", is_clarify=True),
    ]
    field = extract_field_for_question(question, turns, threshold=0.7)
    assert field.value == 2050.0
    assert field.needs_human_review is False


def test_genuine_contradiction_is_flagged_not_coin_flipped() -> None:
    question = Question(id="rent", prompt="P?", answer_type=AnswerType.FLOAT)
    turns = [
        _human_turn(1, "It's $1,800 a month.", "rent"),
        _human_turn(2, "It's $2,200 a month.", "rent", is_clarify=True),
    ]
    field = extract_field_for_question(question, turns, threshold=0.7)
    assert field.value is None
    assert field.needs_human_review is True
    assert "contradictory" in (field.reason or "")
