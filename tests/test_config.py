from __future__ import annotations

from app.config import Settings


def test_settings_load_with_mock_defaults():
    settings = Settings()
    assert settings.llm_provider == "fake"
    assert settings.telephony_provider == "mock"
    assert settings.stt_provider == "mock"
    assert settings.tts_provider == "mock"
    assert "proxy" in settings.database_url
