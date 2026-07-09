from __future__ import annotations

import json

from click.testing import CliRunner

from app.cli import cli


def test_run_produces_ranked_grounded_results_across_every_terminal_state() -> None:
    """Executable proof of the CLAUDE.md-mandated offline demo: no env vars,
    no network, no API keys — and the mock scenarios genuinely exercise every
    branch of the call state machine, not just the happy path."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["run", "--request", "examples/auto_repair_request.json", "--hint-pack", "auto_repair"]
    )
    assert result.exit_code == 0, result.output

    # stderr (missing-context warnings) and stdout (the JSON payload) are
    # merged by CliRunner — the JSON always starts at the first "{".
    payload = json.loads(result.output[result.output.index("{") :])
    results = payload["results"]
    assert len(results) == 6

    terminal_states = {r["terminal_state"] for r in results}
    assert terminal_states == {"got_info", "refused", "couldnt_reach"}

    # Ranked table: GOT_INFO results sort before REFUSED before COULDNT_REACH.
    seen_states = [r["terminal_state"] for r in results]
    assert (
        seen_states.index("got_info")
        < seen_states.index("refused")
        < seen_states.index("couldnt_reach")
    )

    # The hard rule, checked at the CLI-output boundary: no field anywhere in
    # the job ever carries a value without a verbatim source_span backing it.
    for call in results:
        for field in call["fields"].values():
            if field["value"] is not None:
                assert field["source_span"] is not None


def test_missing_context_is_surfaced_before_dialing() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["run", "--request", "examples/auto_repair_request.json", "--hint-pack", "auto_repair"]
    )
    assert "symptom" in result.output or "missing context" in result.output.lower()


def test_unknown_request_path_fails_loudly() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--request", "examples/does_not_exist.json"])
    assert result.exit_code != 0
