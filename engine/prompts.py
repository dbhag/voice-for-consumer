"""Filesystem loader for versioned prompt files.

Prompts are code: they live under `prompts/<vertical_id>/<version>/<name>.txt`
and are never inlined as Python string literals.
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(vertical_id: str, name: str, version: str = "v1") -> str:
    path = PROMPTS_ROOT / vertical_id / version / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"No prompt file at {path}")
    return path.read_text(encoding="utf-8").strip()
