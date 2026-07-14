from __future__ import annotations

import pytest

from app.config import Settings
from app.providers import build_provider_bundle
from engine.providers.llm_extraction import LLMExtractionProvider
from engine.providers.llm_pre_call_brief import LLMPreCallBriefProvider
from engine.providers.mock import (
    MockExtractionProvider,
    MockPreCallBriefProvider,
    MockVoicePlatformProvider,
)
from engine.providers.retell import RetellVoicePlatformProvider


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
    # voice_platform_provider still defaults to "mock" independent of llm_provider.
    assert isinstance(bundle.voice_platform, MockVoicePlatformProvider)


def test_uses_real_anthropic_providers_when_configured() -> None:
    settings = Settings(llm_provider="anthropic", anthropic_api_key="sk-ant-test")
    bundle = build_provider_bundle(settings)

    assert isinstance(bundle.extraction, LLMExtractionProvider)
    assert isinstance(bundle.pre_call_brief, LLMPreCallBriefProvider)


def test_falls_back_to_mock_voice_platform_without_an_api_key() -> None:
    settings = Settings(voice_platform_provider="retell", retell_from_number="+15551110000")
    bundle = build_provider_bundle(settings)

    assert isinstance(bundle.voice_platform, MockVoicePlatformProvider)


def test_uses_real_retell_provider_when_configured() -> None:
    settings = Settings(
        voice_platform_provider="retell",
        voice_platform_api_key="retell-key",
        retell_from_number="+15551110000",
        retell_agent_id="agent_abc",
    )
    bundle = build_provider_bundle(settings, hint_pack={"field_labels": {"price": "the price"}})

    assert isinstance(bundle.voice_platform, RetellVoicePlatformProvider)


def test_retell_without_from_number_raises() -> None:
    settings = Settings(voice_platform_provider="retell", voice_platform_api_key="retell-key")

    with pytest.raises(ValueError, match="retell_from_number"):
        build_provider_bundle(settings)
