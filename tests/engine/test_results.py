from __future__ import annotations

from datetime import UTC, datetime

from engine.models import CallResult, CompletionLevel, ReachFailure, TerminalState
from engine.results import rank_results


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
