import asyncio
import json

import click
from pydantic import TypeAdapter

from app.config import settings
from engine.models import Target
from engine.orchestrator import run_job
from engine.providers.base import ProviderBundle
from engine.providers.mock import (
    MockDialogueLLMProvider,
    MockExtractionProvider,
    MockTelephonyProvider,
)
from engine.results import build_results
from verticals.registry import get_vertical


@click.group()
def cli() -> None:
    """Proxy command-line interface."""


@cli.command("run")
@click.option("--vertical", "vertical_id", required=True, help="Vertical id, e.g. 'rental'.")
@click.option(
    "--targets", required=True, type=click.Path(exists=True), help="Path to targets JSON."
)
def run(vertical_id: str, targets: str) -> None:
    """Run a job locally against mock telephony/dialogue/extraction providers."""
    vertical = get_vertical(vertical_id)

    with open(targets, encoding="utf-8") as f:
        raw_targets = json.load(f)
    target_list = TypeAdapter(list[Target]).validate_python(raw_targets)

    providers = ProviderBundle(
        telephony=MockTelephonyProvider(),
        dialogue=MockDialogueLLMProvider(),
        extraction=MockExtractionProvider(threshold=settings.confidence_threshold),
    )

    results = asyncio.run(run_job(vertical, target_list, providers))
    output = build_results(vertical, results)
    click.echo(output.model_dump_json(indent=2))


if __name__ == "__main__":
    cli()
