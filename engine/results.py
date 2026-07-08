"""Build the vertical's declared result shape from a batch of call results."""

from __future__ import annotations

from engine.models import CallResult, ComparisonResult, SingleResult, Vertical


def build_results(vertical: Vertical, results: list[CallResult]) -> ComparisonResult | SingleResult:
    if vertical.result_mode == "compare":
        return ComparisonResult(vertical_id=vertical.id, results=results)
    if len(results) != 1:
        raise ValueError(
            f"result_mode='single' requires exactly one CallResult, got {len(results)}"
        )
    return SingleResult(vertical_id=vertical.id, result=results[0])
