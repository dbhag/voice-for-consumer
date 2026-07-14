"""Selects real vs. mock providers from settings — the seam that makes
"production-ready except the voice vendor" literally true. Extraction and
the pre-call brief already have real OpenAI/Anthropic implementations
(`engine/providers/llm_*.py`); flipping `llm_provider` + an API key turns
them on. `voice_platform` defaults to mocked and switches to the real
`RetellVoicePlatformProvider` once `voice_platform_provider="retell"` and
an API key are configured.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from engine.providers.base import (
    ExtractionProvider,
    PreCallBriefProvider,
    ProviderBundle,
    VoicePlatformProvider,
)
from engine.providers.hard_rule_audit import HardRuleAuditProvider, LLMHardRuleAuditProvider
from engine.providers.llm_extraction import LLMExtractionProvider
from engine.providers.llm_pre_call_brief import LLMPreCallBriefProvider
from engine.providers.mock import (
    MockExtractionProvider,
    MockPreCallBriefProvider,
    MockVoicePlatformProvider,
)
from engine.providers.retell import RetellVoicePlatformProvider


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


def _build_voice_platform(
    settings: Settings, hint_pack: dict[str, Any] | None
) -> VoicePlatformProvider:
    if settings.voice_platform_provider == "retell" and settings.voice_platform_api_key:
        if not settings.retell_from_number:
            raise ValueError("voice_platform_provider=retell requires retell_from_number")
        return RetellVoicePlatformProvider(
            api_key=settings.voice_platform_api_key,
            from_number=settings.retell_from_number,
            base_url=settings.voice_platform_base_url,
            agent_id=settings.retell_agent_id,
            hint_pack=hint_pack,
        )
    return MockVoicePlatformProvider()


def build_hard_rule_audit_provider(settings: Settings) -> HardRuleAuditProvider | None:
    """None — not a mock — when no LLM is configured: `app.cli report`
    reports "not audited" rather than silently defaulting to a provider that
    would always say clean. Not part of ProviderBundle: the audit runs
    post-hoc over a persisted job (app.cli report), never during
    engine.orchestrator.run_job.
    """
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return LLMHardRuleAuditProvider("openai", settings.openai_api_key)
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        return LLMHardRuleAuditProvider("anthropic", settings.anthropic_api_key)
    return None


def build_provider_bundle(
    settings: Settings, hint_pack: dict[str, Any] | None = None
) -> ProviderBundle:
    """`hint_pack` only matters for a real voice-platform adapter that must
    front-load context at call-creation time (e.g. Retell's
    retell_llm_dynamic_variables) — see engine/providers/retell.py. Mock and
    the other two providers ignore it; existing callers that don't pass it
    are unaffected.
    """
    return ProviderBundle(
        voice_platform=_build_voice_platform(settings, hint_pack),
        pre_call_brief=_build_pre_call_brief(settings),
        extraction=_build_extraction(settings),
    )
