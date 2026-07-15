from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "fake"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # The ONE bought voice-infra platform (telephony + STT + TTS + turn-taking
    # as a single product) behind engine.providers.base.VoicePlatformProvider.
    # "mock" backs engine.providers.mock.MockVoicePlatformProvider; "retell"
    # backs engine.providers.retell.RetellVoicePlatformProvider.
    voice_platform_provider: str = "mock"
    voice_platform_api_key: str | None = None
    voice_platform_base_url: str | None = None
    retell_agent_id: str | None = None
    retell_from_number: str | None = None

    concurrency_cap: int = 5
    # Placeholders — not calibrated against real per-minute vendor pricing or
    # observed hold durations yet. Needs real data before production.
    job_minute_budget: float = 30.0
    hold_abandon_seconds: float = 180.0

    database_url: str = "postgresql+asyncpg://proxy:proxy@localhost:5432/proxy"
    redis_url: str = "redis://localhost:6379/0"

    # Comma-separated allowed origins for the dashboard's browser-side fetch
    # calls (app/main.py's CORSMiddleware). dev.sh derives this from
    # DASHBOARD_PORT so it stays correct if that port is overridden.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Async completion ping (CLAUDE.md's Stack table: "SMS (Twilio) or
    # email"). "mock" backs app.notifications.MockNotificationProvider;
    # "email" sends for real via stdlib smtplib.
    notification_provider: str = "mock"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None


settings = Settings()
