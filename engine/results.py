"""Ranks a job's call results for the P0 "ranked results table" per
CLAUDE.md. The request object no longer carries a per-vertical result mode
(compare vs. single) — a job always produces one ranked list of CallResults.
"""

from __future__ import annotations

from engine.models import CallResult, CompletionLevel, TerminalState

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
