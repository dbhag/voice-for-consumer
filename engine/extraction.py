"""The hard rule's structural enforcement point.

`ground_field` is the single choke point every extraction path (mock or
real) must go through: a value can never be attached without a verbatim
`source_span`. If nothing in the transcript backs a fact, the field stays
unknown — never a guess.
"""

from __future__ import annotations

from typing import Any

from engine.models import FieldResult


def ground_field(
    value: Any,
    source_span: str | None,
    *,
    reason: str | None = None,
    confidence: float | None = None,
) -> FieldResult:
    if value is not None and source_span is None:
        raise ValueError("hallucination guard: cannot set value without source_span")
    return FieldResult(value=value, source_span=source_span, reason=reason, confidence=confidence)
