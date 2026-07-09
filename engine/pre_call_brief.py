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
