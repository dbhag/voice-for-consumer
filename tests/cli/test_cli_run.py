from __future__ import annotations

import json

from click.testing import CliRunner

from app.cli import cli


def test_run_produces_confidence_scored_json_with_flagged_fields() -> None:
    """Executable proof of the CLAUDE.md-mandated offline demo: no env vars,
    no network, no API keys — and the mock scenarios genuinely exercise
    ambiguity/refusal, not just the happy path."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["run", "--vertical", "rental", "--targets", "examples/rental_targets.json"]
    )
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["vertical_id"] == "rental"
    assert len(payload["results"]) == 3

    flagged = [
        (call["target"]["id"], field_name)
        for call in payload["results"]
        for field_name, field in call["extracted"].items()
        if field["needs_human_review"]
    ]
    assert flagged, "expected at least one field flagged for human review across the mock run"

    declined = [
        (call["target"]["id"], field_name)
        for call in payload["results"]
        for field_name, field in call["extracted"].items()
        if field["reason"] == "declined"
    ]
    assert declined, "expected the refusal scenario (t3 security_deposit) to surface as declined"


def test_unknown_vertical_fails_loudly() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["run", "--vertical", "does_not_exist", "--targets", "examples/rental_targets.json"]
    )
    assert result.exit_code != 0
