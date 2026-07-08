"""Thin arq task wrapper around the engine orchestrator. Importable only in
this pass — not registered in a `WorkerSettings`, not invoked by any command.
`app.cli run` calls `engine.orchestrator.run_job` directly instead.
"""

from __future__ import annotations

from typing import Any

from engine.models import CallResult, Target, Vertical
from engine.orchestrator import run_job
from engine.providers.base import ProviderBundle


async def run_job_task(
    ctx: dict[str, Any], vertical: Vertical, targets: list[Target], providers: ProviderBundle
) -> list[CallResult]:
    return await run_job(vertical, targets, providers)
