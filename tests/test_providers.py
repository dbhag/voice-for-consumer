from __future__ import annotations

from app.config import Settings
from app.providers import build_provider_bundle
from engine.providers.llm_extraction import LLMExtractionProvider
from engine.providers.llm_pre_call_brief import LLMPreCallBriefProvider
from engine.providers.mock import (
    MockExtractionProvider,
    MockPreCallBriefProvider,
    MockVoicePlatformProvider,
)


def test_defaults_to_mock_everywhere() -> None:
    bundle = build_provider_bundle(Settings())

    assert isinstance(bundle.voice_platform, MockVoicePlatformProvider)
    assert isinstance(bundle.extraction, MockExtractionProvider)
    assert isinstance(bundle.pre_call_brief, MockPreCallBriefProvider)


def test_falls_back_to_mock_without_an_api_key_even_if_provider_named() -> None:
    bundle = build_provider_bundle(Settings(llm_provider="openai"))

    assert isinstance(bundle.extraction, MockExtractionProvider)
    assert isinstance(bundle.pre_call_brief, MockPreCallBriefProvider)


def test_uses_real_openai_providers_when_configured() -> None:
    settings = Settings(llm_provider="openai", openai_api_key="sk-test")
    bundle = build_provider_bundle(settings)

    assert isinstance(bundle.extraction, LLMExtractionProvider)
    assert isinstance(bundle.pre_call_brief, LLMPreCallBriefProvider)
    # Voice platform is never real — vendor choice is deliberately deferred.
    assert isinstance(bundle.voice_platform, MockVoicePlatformProvider)


def test_uses_real_anthropic_providers_when_configured() -> None:
    settings = Settings(llm_provider="anthropic", anthropic_api_key="sk-ant-test")
    bundle = build_provider_bundle(settings)

    assert isinstance(bundle.extraction, LLMExtractionProvider)
    assert isinstance(bundle.pre_call_brief, LLMPreCallBriefProvider)
