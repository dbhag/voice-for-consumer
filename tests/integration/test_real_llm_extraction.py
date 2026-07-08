"""Opt-in, developer-run only. Exercises the real structured-output
LLMExtractionProvider against a fixed sample transcript. Never runs in CI —
requires OPENAI_API_KEY or ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import os

import pytest

from engine.models import TranscriptTurn
from engine.providers.llm_extraction import LLMExtractionProvider
from verticals.rental.config import build_rental_vertical

pytestmark = pytest.mark.integration

_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")


@pytest.mark.skipif(_API_KEY is None, reason="requires OPENAI_API_KEY or ANTHROPIC_API_KEY")
async def test_llm_extraction_against_sample_transcript() -> None:
    provider_name = "openai" if os.environ.get("OPENAI_API_KEY") else "anthropic"
    assert _API_KEY is not None

    vertical = build_rental_vertical()
    transcript = [
        TranscriptTurn(turn_id=0, speaker="agent", text=vertical.disclosure_script),
        TranscriptTurn(
            turn_id=1, speaker="agent", text="What's the monthly rent?", question_id="monthly_rent"
        ),
        TranscriptTurn(
            turn_id=2, speaker="human", text="It's $1,800 a month.", question_id="monthly_rent"
        ),
    ]
    extractor = LLMExtractionProvider(provider=provider_name, api_key=_API_KEY)
    result = await extractor.extract(vertical, transcript)
    assert result is not None
