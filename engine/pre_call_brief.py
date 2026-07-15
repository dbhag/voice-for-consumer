"""The pre-call brief: highest-leverage P0 feature per CLAUDE.md. Turns an
ask into a primary question, return fields, likely follow-ups, and a
missing-context check surfaced to the user *before* dialing.
"""

from __future__ import annotations

from typing import Any

from engine.models import MissingContext


def missing_context_fields(
    context: dict[str, Any], hint_pack: dict[str, Any] | None
) -> list[MissingContext]:
    """Data-driven completeness check — hint packs are plain data, never a
    vertical branch in this function or anywhere else in engine/.
    """
    if not hint_pack:
        return []
    likely_fields: list[dict[str, str]] = hint_pack.get("likely_follow_up_fields", [])
    missing = []
    for field in likely_fields:
        key = field["key"]
        if key not in context or context[key] in (None, ""):
            missing.append(MissingContext(field=key, prompt=field["prompt"]))
    return missing


# Demo-only keyword heuristic, mirroring the judgment call the real
# LLM-backed brief (engine/providers/llm_pre_call_brief.py) makes — same
# status as MockExtractionProvider's keyword heuristics in
# engine/providers/mock.py: never load-bearing in production, just enough
# fidelity for the mock provider to exercise and demo the same three-way
# behavior (real fact / resolvable non-answer / unresolvable non-answer).
_NON_ANSWER_PHRASES = {
    "not sure", "n/a", "na", "idk", "dont know", "don't know",
    "no idea", "unsure", "unknown", "none", "-", "?",
}


def detect_non_answer_context(
    context: dict[str, Any], hint_pack: dict[str, Any] | None
) -> tuple[list[MissingContext], list[str]]:
    """A context value must be a stated fact, never a non-answer like "not
    sure" or "n/a" — those must never reach the agent as if the user had
    actually answered. Returns (resurfaced, dropped): every flagged key
    goes in `dropped` (it must never enter the call's context); a key also
    goes in `resurfaced` (same missing_context shape as a blank field) only
    if the hint pack has a real prompt for it — i.e. the user could
    plausibly go find the real answer. A key with no hint-pack entry has
    nothing sensible to ask, so it's dropped silently rather than
    re-prompted for no reason.
    """
    known_prompts: dict[str, str] = {
        f["key"]: f["prompt"] for f in (hint_pack or {}).get("likely_follow_up_fields", [])
    }
    resurfaced: list[MissingContext] = []
    dropped: list[str] = []
    for key, value in context.items():
        if not isinstance(value, str) or value.strip().lower() not in _NON_ANSWER_PHRASES:
            continue
        dropped.append(key)
        if key in known_prompts:
            resurfaced.append(MissingContext(field=key, prompt=known_prompts[key]))
    return resurfaced, dropped
