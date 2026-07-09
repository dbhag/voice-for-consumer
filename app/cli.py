from __future__ import annotations

import asyncio
import json

import click

from app.config import settings
from engine.cache import InMemoryCacheStore
from engine.hint_packs import load_hint_pack
from engine.models import Request
from engine.orchestrator import run_job
from engine.providers.base import ProviderBundle
from engine.providers.mock import (
    MockExtractionProvider,
    MockPreCallBriefProvider,
    MockVoicePlatformProvider,
)
from engine.results import rank_results


@click.group()
def cli() -> None:
    """Proxy command-line interface."""


@cli.command("run")
@click.option(
    "--request",
    "request_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to a Request JSON file.",
)
@click.option(
    "--hint-pack", "hint_pack_name", default=None, help="Hint pack id, e.g. 'auto_repair'."
)
def run(request_path: str, hint_pack_name: str | None) -> None:
    """Run a job locally against mock voice-platform/extraction providers."""
    with open(request_path, encoding="utf-8") as f:
        request = Request.model_validate_json(f.read())

    hint_pack = load_hint_pack(hint_pack_name) if hint_pack_name else None

    providers = ProviderBundle(
        voice_platform=MockVoicePlatformProvider(),
        pre_call_brief=MockPreCallBriefProvider(),
        extraction=MockExtractionProvider(),
    )

    brief = asyncio.run(providers.pre_call_brief.build_brief(request, hint_pack))
    for missing in brief.missing_context:
        click.echo(f"[missing context] {missing.prompt}", err=True)

    cache = InMemoryCacheStore()
    job_result = asyncio.run(
        run_job(
            request,
            providers,
            cache,
            settings.concurrency_cap,
            settings.job_minute_budget,
            settings.hold_abandon_seconds,
        )
    )
    ranked = rank_results(job_result.results)

    output = {
        "request": job_result.request.model_dump(mode="json"),
        "results": [r.model_dump(mode="json") for r in ranked],
    }
    click.echo(json.dumps(output, indent=2))


if __name__ == "__main__":
    cli()
