from __future__ import annotations

from engine.prompts import PROMPTS_ROOT
from verticals.rental.config import build_rental_vertical


def test_rental_vertical_is_valid() -> None:
    vertical = build_rental_vertical()
    assert vertical.id == "rental"
    assert vertical.result_mode == "compare"
    assert vertical.question_set


def test_question_ids_are_unique() -> None:
    vertical = build_rental_vertical()
    ids = [q.id for q in vertical.question_set]
    assert len(ids) == len(set(ids))


def test_extraction_schema_has_one_field_per_question() -> None:
    vertical = build_rental_vertical()
    assert set(vertical.extraction_schema.model_fields) == {q.id for q in vertical.question_set}


def test_disclosure_script_matches_prompt_file_verbatim() -> None:
    """Regression guard against inlining the disclosure text in config.py —
    the legally-sensitive script must stay versioned and diffable."""
    vertical = build_rental_vertical()
    on_disk = (PROMPTS_ROOT / "rental" / "v1" / "disclosure.txt").read_text(encoding="utf-8").strip()
    assert vertical.disclosure_script == on_disk
