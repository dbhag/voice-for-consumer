from __future__ import annotations

from engine.models import Request


def _request(return_fields: list[str]) -> Request:
    return Request(
        ask="quote for front brake pad replacement",
        return_fields=return_fields,
        targets=["+15550000001"],
    )


def test_plain_language_field_name_is_slugified() -> None:
    assert _request(["earliest availability"]).return_fields == ["earliest_availability"]


def test_already_snake_case_field_name_is_left_alone() -> None:
    assert _request(["parts_vs_labor"]).return_fields == ["parts_vs_labor"]


def test_compound_field_joined_by_and_is_split_into_separate_fields() -> None:
    # The real incident this guards against: a caller who doesn't
    # comma-separate ("price and tour availability" typed as one entry)
    # must not end up with one merged field whose "value" is a whole
    # paragraph instead of one grounded fact each.
    request = _request(["price and tour availability"])
    assert request.return_fields == ["price", "tour_availability"]


def test_compound_field_is_split_before_slugifying_not_after() -> None:
    # A field name that's already underscore-joined has no word boundary
    # left for "and" to split on ("_" counts as a word character) — the
    # split has to happen on the raw, pre-slugified string.
    request = _request(["price_and_tour_availability"])
    assert request.return_fields == ["price_and_tour_availability"]


def test_multiple_compound_fields_each_split_independently() -> None:
    request = _request(["price and parts vs labor", "earliest availability"])
    assert request.return_fields == ["price", "parts_vs_labor", "earliest_availability"]


def test_ampersand_and_as_well_as_are_also_treated_as_compound_delimiters() -> None:
    request = _request(["price & availability", "make as well as model"])
    assert request.return_fields == ["price", "availability", "make", "model"]


def test_and_inside_a_word_is_not_treated_as_a_delimiter() -> None:
    # "brand" contains "and" as a substring, not the word "and" — must not
    # be split mid-word.
    request = _request(["brand"])
    assert request.return_fields == ["brand"]
