from __future__ import annotations

import asyncio
import json
import sys

import click

from app.config import settings
from app.db import repository
from app.db.session import make_engine, make_session_factory
from app.providers import build_hard_rule_audit_provider
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
from engine.results import rank_results, render_job_report_markdown


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


@cli.command("report")
@click.argument("job_id")
@click.option(
    "--database-url",
    "database_url",
    default=None,
    help="Override settings.database_url (e.g. a local sqlite file for testing).",
)
def report(job_id: str, database_url: str | None) -> None:
    """Dump a completed job as a markdown table: target, terminal state,
    reason, grounded/unknown return_fields, hold seconds, call minutes,
    cost, and a hard-rule audit column. Reads from the persisted DB (the
    job must have gone through POST /jobs + the arq worker, not `cli run`'s
    in-memory demo path).
    """
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)

    async def _report() -> str | None:
        async with session_factory() as session:
            status_and_result = await repository.get_job(session, job_id)
        await engine.dispose()

        if status_and_result is None:
            click.echo(f"No such job: {job_id}", err=True)
            return None
        status, job_result = status_and_result
        if job_result is None:
            click.echo(f"Job {job_id} is not done yet (status: {status})", err=True)
            return None

        audit_provider = build_hard_rule_audit_provider(settings)
        if audit_provider is None:
            click.echo(
                "[no LLM configured — hard-rule column will read 'not audited']", err=True
            )
        return await render_job_report_markdown(job_id, job_result, audit_provider)

    markdown = asyncio.run(_report())
    if markdown is None:
        sys.exit(1)
    click.echo(markdown)


if __name__ == "__main__":
    cli()
