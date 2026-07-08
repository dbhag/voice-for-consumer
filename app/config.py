from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "fake"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    telephony_provider: str = "mock"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None

    stt_provider: str = "mock"
    deepgram_api_key: str | None = None

    tts_provider: str = "mock"
    cartesia_api_key: str | None = None
    elevenlabs_api_key: str | None = None

    confidence_threshold: float = 0.7

    database_url: str = "postgresql+asyncpg://proxy:proxy@localhost:5432/proxy"
    redis_url: str = "redis://localhost:6379/0"


settings = Settings()
