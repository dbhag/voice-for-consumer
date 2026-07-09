from __future__ import annotations

from app.config import Settings


def test_settings_load_with_mock_defaults() -> None:
    settings = Settings()
    assert settings.llm_provider == "fake"
    assert settings.voice_platform_provider == "mock"
    assert "proxy" in settings.database_url
