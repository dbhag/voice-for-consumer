"""Confidence-gated extraction primitives.

`make_extracted_field` is the single choke point that enforces the two
non-negotiable rules from CLAUDE.md: no value without a source_span
(hallucination guard), and `needs_human_review` is always *computed* from
the confidence threshold, never hand-set by a caller.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from engine.models import AnswerType, ExtractedField, Question, TranscriptTurn

REFUSAL_KEYWORDS = (
    "not able to share",
    "can't tell you",
    "cannot tell you",
    "no comment",
    "prefer not to say",
    "can't disclose",
    "cannot disclose",
    "not allowed to say",
)

HEDGE_KEYWORDS = (
    "around",
    "ish",
    "depends",
    "roughly",
    "not sure",
    "maybe",
    "approximately",
    "give or take",
)

_NUMBER_RE = re.compile(r"\$?\s?(\d[\d,]*(?:\.\d+)?)")
_MONTH_DAY_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2})(?:st|nd|rd|th)?",
    re.IGNORECASE,
)


def is_refusal(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in REFUSAL_KEYWORDS)


def is_hedge(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in HEDGE_KEYWORDS)


def make_extracted_field(
    *,
    value: Any,
    confidence: float,
    source_span: str | None,
    reason: str | None,
    threshold: float,
) -> ExtractedField[Any]:
    if value is not None and source_span is None:
        raise ValueError("hallucination guard: cannot set value without source_span")
    return ExtractedField(
        value=value,
        confidence=confidence,
        source_span=source_span,
        needs_human_review=confidence < threshold,
        reason=reason,
    )


def parse_value(question: Question, text: str) -> Any | None:
    """Best-effort deterministic parse. Returns None on failure — never guesses."""
    if question.answer_type is AnswerType.FLOAT:
        match = _NUMBER_RE.search(text)
        return float(match.group(1).replace(",", "")) if match else None

    if question.answer_type is AnswerType.INT:
        match = _NUMBER_RE.search(text)
        return int(float(match.group(1).replace(",", ""))) if match else None

    if question.answer_type is AnswerType.BOOL:
        lowered = text.lower()
        if "yes" in lowered:
            return True
        if "no" in lowered:
            return False
        return None

    if question.answer_type is AnswerType.DATE:
        match = _MONTH_DAY_RE.search(text)
        if not match:
            return None
        month_str, day_str = match.group(1), match.group(2)
        month = None
        for fmt in ("%B", "%b"):
            try:
                month = datetime.strptime(month_str, fmt).month
                break
            except ValueError:
                continue
        if month is None:
            return None
        try:
            return date(date.today().year, month, int(day_str))
        except ValueError:
            return None

    if question.answer_type is AnswerType.ENUM:
        lowered = text.lower()
        values = question.enum_values or []
        if "all" in lowered and "included" in lowered:
            candidate = "all_included"
        elif "none" in lowered or "not included" in lowered:
            candidate = "none_included"
        elif "included" in lowered:
            candidate = "some_included"
        else:
            candidate = "unknown"
        return candidate if candidate in values else None

    # STR
    return text.strip() or None


def extract_field_for_question(
    question: Question, turns: list[TranscriptTurn], threshold: float
) -> ExtractedField[Any]:
    grouped = [t for t in turns if t.speaker == "human" and t.question_id == question.id]
    if not grouped:
        return make_extracted_field(
            value=None,
            confidence=0.0,
            source_span=None,
            reason="no answer captured",
            threshold=threshold,
        )

    primary = next((t for t in grouped if not t.is_clarify), grouped[0])
    clarify = next((t for t in grouped if t.is_clarify), None)

    if clarify and is_refusal(clarify.text):
        refusal_turn = clarify
    elif is_refusal(primary.text):
        refusal_turn = primary
    else:
        refusal_turn = None
    if refusal_turn is not None:
        return make_extracted_field(
            value=None,
            confidence=1.0,
            source_span=refusal_turn.text,
            reason="declined",
            threshold=threshold,
        )

    primary_value = parse_value(question, primary.text)

    if clarify is None:
        if primary_value is None:
            return make_extracted_field(
                value=None,
                confidence=0.2,
                source_span=primary.text,
                reason="could not parse answer",
                threshold=threshold,
            )
        return make_extracted_field(
            value=primary_value,
            confidence=0.95,
            source_span=primary.text,
            reason=None,
            threshold=threshold,
        )

    clarify_value = parse_value(question, clarify.text)
    if clarify_value is None:
        return make_extracted_field(
            value=None,
            confidence=0.2,
            source_span=clarify.text,
            reason="could not parse clarifying answer",
            threshold=threshold,
        )

    # A clarify turn always follows an ambiguous primary answer. If the
    # primary was hedged, the clarify *refines* it rather than contradicting
    # it — only a confidently-stated primary that disagrees with the
    # clarify counts as a genuine contradiction we must flag rather than
    # silently resolve.
    if primary_value is not None and not is_hedge(primary.text) and primary_value != clarify_value:
        return make_extracted_field(
            value=None,
            confidence=0.3,
            source_span=f"{primary.text} | {clarify.text}",
            reason=f"contradictory answers: {primary.text!r} vs {clarify.text!r}",
            threshold=threshold,
        )

    return make_extracted_field(
        value=clarify_value,
        confidence=0.9,
        source_span=clarify.text,
        reason=None,
        threshold=threshold,
    )
