from __future__ import annotations

from engine.pre_call_brief import detect_non_answer_context, missing_context_fields

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


def test_real_fact_is_neither_resurfaced_nor_dropped() -> None:
    resurfaced, dropped = detect_non_answer_context({"car": "2018 Civic"}, HINT_PACK)
    assert resurfaced == []
    assert dropped == []


def test_non_answer_for_a_known_field_is_resurfaced_and_dropped() -> None:
    resurfaced, dropped = detect_non_answer_context({"mileage": "not sure"}, HINT_PACK)
    assert [m.field for m in resurfaced] == ["mileage"]
    assert resurfaced[0].prompt == "add mileage?"
    assert dropped == ["mileage"]


def test_non_answer_for_an_unknown_field_is_dropped_only_not_resurfaced() -> None:
    # No hint-pack prompt exists for a freely-typed key the user added
    # themselves — nothing sensible to ask again, so it's just dropped.
    resurfaced, dropped = detect_non_answer_context({"deductible": "n/a"}, HINT_PACK)
    assert resurfaced == []
    assert dropped == ["deductible"]


def test_non_string_values_are_never_flagged() -> None:
    resurfaced, dropped = detect_non_answer_context({"mileage": 0}, HINT_PACK)
    assert resurfaced == []
    assert dropped == []


def test_non_answer_matching_is_case_and_whitespace_insensitive() -> None:
    resurfaced, dropped = detect_non_answer_context({"mileage": "  N/A  "}, HINT_PACK)
    assert dropped == ["mileage"]
    assert [m.field for m in resurfaced] == ["mileage"]
