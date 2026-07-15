"""Loader for hint packs — plain data, never a vertical branch in code.

A hint pack enriches the pre-call brief's missing-context check (e.g. "auto
repair shops will likely ask year/make/model/mileage"). Adding a new
vertical means adding a new JSON file here, never touching engine/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HINT_PACKS_ROOT = Path(__file__).resolve().parent.parent / "hint_packs"


def load_hint_pack(name: str) -> dict[str, Any] | None:
    path = HINT_PACKS_ROOT / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def select_hint_pack(ask: str) -> str | None:
    """Best-effort hint-pack match against the free-text ask, so a caller
    (the dashboard) never has to name a pack explicitly. Still data-driven,
    not a vertical branch: `match_keywords` lives in each pack's own JSON,
    this just does generic keyword-overlap scoring across whatever packs
    exist. Returns the pack with the most keyword hits, or None if nothing
    scores above zero — callers should treat that as "no enrichment
    available," not an error.
    """
    ask_lower = ask.lower()
    best_name: str | None = None
    best_score = 0
    for path in sorted(HINT_PACKS_ROOT.glob("*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        keywords: list[str] = pack.get("match_keywords", [])
        score = sum(1 for kw in keywords if kw.lower() in ask_lower)
        if score > best_score:
            best_score = score
            best_name = path.stem
    return best_name
