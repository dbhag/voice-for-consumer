"""Opt-in, developer-run only. Exercises the real structured-output
LLMExtractionProvider against a fixed sample transcript. Never runs in CI —
requires OPENAI_API_KEY or ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import os
from typing import Literal

import pytest

from engine.models import TranscriptTurn
from engine.providers.llm_extraction import LLMExtractionProvider

pytestmark = pytest.mark.integration

_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")


@pytest.mark.skipif(not _API_KEY, reason="requires OPENAI_API_KEY or ANTHROPIC_API_KEY")
async def test_llm_extraction_against_sample_transcript() -> None:
    provider_name: Literal["openai", "anthropic"] = (
        "openai" if os.environ.get("OPENAI_API_KEY") else "anthropic"
    )
    assert _API_KEY

    transcript = [
        TranscriptTurn(
            turn_id=0,
            speaker="agent",
            text="Hi, this is Proxy, an AI assistant calling on behalf of a customer.",
        ),
        TranscriptTurn(
            turn_id=1,
            speaker="agent",
            text="I'm calling for a quote on front brake pad replacement for a 2018 Honda Civic.",
        ),
        TranscriptTurn(
            turn_id=2,
            speaker="human",
            text="Sure — that'll be $220 for parts and labor, mostly labor.",
        ),
    ]
    extractor = LLMExtractionProvider(provider=provider_name, api_key=_API_KEY)
    result = await extractor.extract(["price", "parts_vs_labor"], transcript)
    assert result["price"].value == pytest.approx(220.0)
