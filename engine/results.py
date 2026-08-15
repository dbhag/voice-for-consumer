"""Ranks a job's call results for the P0 "ranked results table" per
CLAUDE.md. The request object no longer carries a per-vertical result mode
(compare vs. single) — a job always produces one ranked list of CallResults.
"""

from __future__ import annotations

from engine.models import CallResult, CompletionLevel, JobResult, TerminalState
from engine.providers.hard_rule_audit import HardRuleAuditProvider

_TERMINAL_RANK: dict[TerminalState, int] = {
    TerminalState.GOT_INFO: 0,
    TerminalState.REFUSED: 1,
    TerminalState.COULDNT_REACH: 2,
}

_COMPLETION_RANK: dict[CompletionLevel | None, int] = {
    CompletionLevel.FULL: 0,
    CompletionLevel.PARTIAL: 1,
    None: 2,
}


def rank_results(results: list[CallResult]) -> list[CallResult]:
    return sorted(
        results,
        key=lambda r: (_TERMINAL_RANK[r.terminal_state], _COMPLETION_RANK[r.completion_level]),
    )


def _reason_for(result: CallResult) -> str:
    return result.refusal_reason or (
        result.reach_failure.value if result.reach_failure else None
    ) or "—"


def _fields_by_groundedness(result: CallResult) -> tuple[str, str]:
    grounded = ", ".join(name for name, f in result.fields.items() if f.value is not None) or "—"
    unknown = ", ".join(name for name, f in result.fields.items() if f.value is None) or "—"
    return grounded, unknown


def _cost_breakdown_for(result: CallResult) -> str:
    # Per-product total for the whole call (Retell doesn't tag cost by
    # conversation state — see CallResult.cost_breakdown_usd) — sorted by
    # product name for a stable, diffable column, not by cost.
    if not result.cost_breakdown_usd:
        return "n/a"
    return ", ".join(
        f"{product} ${cost:.2f}" for product, cost in sorted(result.cost_breakdown_usd.items())
    )


async def render_job_report_markdown(
    job_id: str, job_result: JobResult, audit_provider: HardRuleAuditProvider | None
) -> str:
    """Per-call log for a completed job, as a markdown table — target,
    terminal state/reason, which return_fields grounded vs. unknown, hold
    seconds, call minutes, cost, and a hard-rule audit column. Consumed by
    `app.cli report`.

    The audit column runs `audit_provider.audit(...)` once per call that has
    a transcript — a real LLM call each time, not free. Calls with no
    transcript (COULDNT_REACH) or when `audit_provider` is None (not
    configured) report "not audited", never a silent "clean" — a check that
    never ran is not the same as a check that passed.
    """
    lines = [
        f'## Job {job_id} — "{job_result.request.ask}"',
        "",
        "| Target | State | Reason | Grounded | Unknown | Hold (s) | Call (min) | Cost |"
        " Cost Breakdown | Hard-Rule |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for result in rank_results(job_result.results):
        state = result.terminal_state.value
        if result.completion_level is not None:
            state += f" ({result.completion_level.value})"
        grounded, unknown = _fields_by_groundedness(result)
        hold = f"{result.hold_seconds:.0f}" if result.hold_seconds is not None else "n/a"
        cost = f"${result.cost_usd:.2f}" if result.cost_usd is not None else "n/a"
        cost_breakdown = _cost_breakdown_for(result)

        if not result.transcript or audit_provider is None:
            hard_rule = "not audited"
        else:
            audit = await audit_provider.audit(result.transcript, job_result.request.context)
            hard_rule = (
                "✅ clean"
                if audit.clean
                else f"**❌ VIOLATION: {audit.violation_detail}**"
            )

        lines.append(
            f"| {result.target} | {state} | {_reason_for(result)} | {grounded} | {unknown} "
            f"| {hold} | {result.call_minutes:.2f} | {cost} | {cost_breakdown} | {hard_rule} |"
        )

    return "\n".join(lines)
