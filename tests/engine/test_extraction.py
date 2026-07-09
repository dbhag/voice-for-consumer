from __future__ import annotations

import pytest

from engine.extraction import ground_field


def test_value_with_source_span_is_allowed() -> None:
    field = ground_field(220.0, "It's $220.")
    assert field.value == 220.0
    assert field.source_span == "It's $220."


def test_none_value_without_source_span_is_allowed() -> None:
    field = ground_field(None, None, reason="declined")
    assert field.value is None
    assert field.source_span is None
    assert field.reason == "declined"


def test_value_without_source_span_raises_the_hallucination_guard() -> None:
    """The hard rule's structural enforcement point (CLAUDE.md: 'it never
    fabricates a user fact') — a value can never be attached to a field
    without a verbatim transcript quote backing it."""
    with pytest.raises(ValueError, match="hallucination guard"):
        ground_field(220.0, None)
