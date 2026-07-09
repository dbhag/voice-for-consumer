"""Selects real vs. mock providers from settings — the seam that makes
"production-ready except the voice vendor" literally true. Extraction and
the pre-call brief already have real OpenAI/Anthropic implementations
(`engine/providers/llm_*.py`); flipping `llm_provider` + an API key turns
them on. `voice_platform` always stays mocked — that's the one
intentionally-deferred piece pending a Bland/Retell/Vapi choice.
"""

from __future__ import annotations

from app.config import Settings
from engine.providers.base import ExtractionProvider, PreCallBriefProvider, ProviderBundle
from engine.providers.llm_extraction import LLMExtractionProvider
from engine.providers.llm_pre_call_brief import LLMPreCallBriefProvider
from engine.providers.mock import (
    MockExtractionProvider,
    MockPreCallBriefProvider,
    MockVoicePlatformProvider,
)


def _build_extraction(settings: Settings) -> ExtractionProvider:
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return LLMExtractionProvider("openai", settings.openai_api_key)
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        return LLMExtractionProvider("anthropic", settings.anthropic_api_key)
    return MockExtractionProvider()


def _build_pre_call_brief(settings: Settings) -> PreCallBriefProvider:
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return LLMPreCallBriefProvider("openai", settings.openai_api_key)
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        return LLMPreCallBriefProvider("anthropic", settings.anthropic_api_key)
    return MockPreCallBriefProvider()


def build_provider_bundle(settings: Settings) -> ProviderBundle:
    return ProviderBundle(
        voice_platform=MockVoicePlatformProvider(),
        pre_call_brief=_build_pre_call_brief(settings),
        extraction=_build_extraction(settings),
    )
