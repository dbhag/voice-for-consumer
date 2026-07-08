from __future__ import annotations

from datetime import UTC, datetime

import pytest

from engine.extraction_schema import build_extraction_schema
from engine.models import AnswerType, CallOutcome, CallResult, Question, Target, Vertical
from engine.results import build_results


def _vertical(result_mode: str) -> Vertical:
    questions = [Question(id="a", prompt="A?", answer_type=AnswerType.STR)]
    return Vertical(
        id="v",
        goal="g",
        disclosure_script="d",
        question_set=questions,
        extraction_schema=build_extraction_schema("v", questions),
        result_mode=result_mode,  # type: ignore[arg-type]
    )


def _call_result(vertical: Vertical, target_id: str) -> CallResult:
    extracted = vertical.extraction_schema(
        a={"value": None, "confidence": 0.0, "source_span": None, "needs_human_review": True, "reason": None}
    )
    return CallResult(
        target=Target(id=target_id, name=target_id, phone_number="+1"),
        outcome=CallOutcome.COMPLETED,
        transcript=[],
        extracted=extracted,
        started_at=datetime.now(UTC),
    )


def test_compare_mode_returns_comparison_result() -> None:
    vertical = _vertical("compare")
    results = [_call_result(vertical, "t1"), _call_result(vertical, "t2")]
    output = build_results(vertical, results)
    assert output.vertical_id == "v"
    assert len(output.results) == 2  # type: ignore[union-attr]


def test_single_mode_returns_single_result() -> None:
    vertical = _vertical("single")
    results = [_call_result(vertical, "t1")]
    output = build_results(vertical, results)
    assert output.result.target.id == "t1"  # type: ignore[union-attr]


def test_single_mode_rejects_anything_but_exactly_one_result() -> None:
    vertical = _vertical("single")
    with pytest.raises(ValueError):
        build_results(vertical, [_call_result(vertical, "t1"), _call_result(vertical, "t2")])
    with pytest.raises(ValueError):
        build_results(vertical, [])
