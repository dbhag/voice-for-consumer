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
