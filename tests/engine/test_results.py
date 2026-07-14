from __future__ import annotations

from datetime import UTC, datetime

from engine.models import (
    CallResult,
    CompletionLevel,
    FieldResult,
    JobResult,
    ReachFailure,
    Request,
    TerminalState,
    TranscriptTurn,
)
from engine.providers.hard_rule_audit import AuditResult
from engine.providers.mock import MockHardRuleAuditProvider
from engine.results import rank_results, render_job_report_markdown


def _result(
    target: str,
    terminal_state: TerminalState,
    completion_level: CompletionLevel | None = None,
) -> CallResult:
    reach_failure = (
        ReachFailure.NO_ANSWER if terminal_state is TerminalState.COULDNT_REACH else None
    )
    return CallResult(
        target=target,
        terminal_state=terminal_state,
        completion_level=completion_level,
        reach_failure=reach_failure,
        started_at=datetime.now(UTC),
    )


def test_got_info_full_ranks_above_partial_above_refused_above_couldnt_reach() -> None:
    couldnt_reach = _result("c", TerminalState.COULDNT_REACH)
    refused = _result("r", TerminalState.REFUSED)
    partial = _result("p", TerminalState.GOT_INFO, CompletionLevel.PARTIAL)
    full = _result("f", TerminalState.GOT_INFO, CompletionLevel.FULL)

    ranked = rank_results([couldnt_reach, refused, partial, full])

    assert [r.target for r in ranked] == ["f", "p", "r", "c"]


def test_rank_results_does_not_mutate_input_order_semantics() -> None:
    results = [
        _result("a", TerminalState.COULDNT_REACH),
        _result("b", TerminalState.GOT_INFO, CompletionLevel.FULL),
    ]
    ranked = rank_results(results)
    assert ranked[0].target == "b"
    assert len(ranked) == len(results)


def _sample_job_request() -> Request:
    return Request(
        ask="quote for front brake pad replacement",
        return_fields=["price", "parts_vs_labor"],
        context={"car": "2018 Honda Civic"},
        targets=["+1", "+2", "+3"],
    )


async def test_report_renders_grounded_and_unknown_fields_hold_cost_and_clean_audit() -> None:
    result = CallResult(
        target="+15550000001",
        terminal_state=TerminalState.GOT_INFO,
        completion_level=CompletionLevel.PARTIAL,
        fields={
            "price": FieldResult(value=220.0, source_span="It's $220."),
            "parts_vs_labor": FieldResult(value=None, source_span=None, reason="not mentioned"),
        },
        transcript=[TranscriptTurn(turn_id=0, speaker="human", text="It's $220.")],
        call_minutes=2.5,
        hold_seconds=45.0,
        cost_usd=0.61,
        started_at=datetime.now(UTC),
    )
    job_result = JobResult(request=_sample_job_request(), results=[result])
    audit_provider = MockHardRuleAuditProvider(AuditResult(clean=True))

    markdown = await render_job_report_markdown("job-1", job_result, audit_provider)

    assert "job-1" in markdown
    assert "+15550000001" in markdown
    assert "got_info (partial)" in markdown
    assert "price" in markdown
    assert "parts_vs_labor" in markdown
    assert "45" in markdown  # hold seconds
    assert "2.50" in markdown  # call minutes
    assert "$0.61" in markdown
    assert "✅ clean" in markdown


async def test_report_renders_violation_prominently() -> None:
    result = CallResult(
        target="+15550000001",
        terminal_state=TerminalState.GOT_INFO,
        completion_level=CompletionLevel.FULL,
        fields={"price": FieldResult(value=220.0, source_span="It's $220.")},
        transcript=[TranscriptTurn(turn_id=0, speaker="agent", text="Your mileage is 82,000.")],
        call_minutes=1.0,
        started_at=datetime.now(UTC),
    )
    job_result = JobResult(request=_sample_job_request(), results=[result])
    audit_provider = MockHardRuleAuditProvider(
        AuditResult(clean=False, violation_detail='agent said "Your mileage is 82,000."')
    )

    markdown = await render_job_report_markdown("job-1", job_result, audit_provider)

    assert "❌ VIOLATION" in markdown
    assert "82,000" in markdown


async def test_report_shows_not_audited_without_an_audit_provider() -> None:
    result = CallResult(
        target="+15550000001",
        terminal_state=TerminalState.GOT_INFO,
        completion_level=CompletionLevel.FULL,
        fields={"price": FieldResult(value=220.0, source_span="It's $220.")},
        transcript=[TranscriptTurn(turn_id=0, speaker="human", text="It's $220.")],
        call_minutes=1.0,
        started_at=datetime.now(UTC),
    )
    job_result = JobResult(request=_sample_job_request(), results=[result])

    markdown = await render_job_report_markdown("job-1", job_result, None)

    assert "not audited" in markdown
    assert "✅" not in markdown


async def test_report_shows_not_audited_for_couldnt_reach_with_no_transcript() -> None:
    result = _result("+15550000002", TerminalState.COULDNT_REACH)
    job_result = JobResult(request=_sample_job_request(), results=[result])
    audit_provider = MockHardRuleAuditProvider(AuditResult(clean=True))

    markdown = await render_job_report_markdown("job-1", job_result, audit_provider)

    assert "not audited" in markdown
    assert "n/a" in markdown  # hold + cost, never dialed


async def test_report_shows_reach_failure_reason_and_dashes_for_no_fields() -> None:
    result = _result("+15550000003", TerminalState.COULDNT_REACH)
    job_result = JobResult(request=_sample_job_request(), results=[result])

    markdown = await render_job_report_markdown("job-1", job_result, None)

    assert "no_answer" in markdown
    lines = [line for line in markdown.splitlines() if "+15550000003" in line]
    assert len(lines) == 1
    assert "—" in lines[0]
