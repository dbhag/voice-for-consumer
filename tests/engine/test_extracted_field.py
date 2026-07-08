from __future__ import annotations

import pytest

from engine.extraction import make_extracted_field


def test_low_confidence_flags_for_review() -> None:
    field = make_extracted_field(value=42.0, confidence=0.5, source_span="quote", reason=None, threshold=0.7)
    assert field.needs_human_review is True


def test_high_confidence_does_not_flag() -> None:
    field = make_extracted_field(value=42.0, confidence=0.9, source_span="quote", reason=None, threshold=0.7)
    assert field.needs_human_review is False


def test_value_without_source_span_raises() -> None:
    with pytest.raises(ValueError, match="hallucination guard"):
        make_extracted_field(value=42.0, confidence=0.9, source_span=None, reason=None, threshold=0.7)


def test_none_value_without_source_span_is_allowed() -> None:
    field = make_extracted_field(value=None, confidence=0.0, source_span=None, reason="declined", threshold=0.7)
    assert field.value is None
    assert field.source_span is None
