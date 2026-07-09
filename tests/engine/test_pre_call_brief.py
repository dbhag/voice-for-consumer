from __future__ import annotations

from engine.pre_call_brief import missing_context_fields

HINT_PACK = {
    "likely_follow_up_fields": [
        {"key": "car", "prompt": "add car?"},
        {"key": "mileage", "prompt": "add mileage?"},
    ]
}


def test_no_hint_pack_means_nothing_flagged_missing() -> None:
    assert missing_context_fields({}, None) == []


def test_flags_only_the_absent_keys() -> None:
    missing = missing_context_fields({"car": "2018 Civic"}, HINT_PACK)
    assert [m.field for m in missing] == ["mileage"]


def test_empty_string_counts_as_missing() -> None:
    missing = missing_context_fields({"car": "", "mileage": 1000}, HINT_PACK)
    assert [m.field for m in missing] == ["car"]


def test_fully_supplied_context_flags_nothing() -> None:
    missing = missing_context_fields({"car": "2018 Civic", "mileage": 82000}, HINT_PACK)
    assert missing == []
