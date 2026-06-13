from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://dental:dental@localhost:5432/dental_clinic"
    database_url_sync: str = "postgresql+psycopg2://dental:dental@localhost:5432/dental_clinic"
    # Plain libpq URL (no SQLAlchemy driver prefix) for the LangGraph Postgres checkpointer (psycopg3).
    database_url_psycopg: str = "postgresql://dental:dental@localhost:5432/dental_clinic"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    anthropic_api_key: str = ""
    llm_model_fast: str = "claude-haiku-4-5-20251001"
    llm_model_escalation: str = "claude-sonnet-4-6"

    # Embeddings
    voyage_api_key: str = ""
    embedding_model: str = "voyage-3.5-lite"
    embedding_dim: int = 512

    # Sarvam
    sarvam_api_key: str = ""

    # LiveKit
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Reminders
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    twilio_sms_from: str = ""

    # Auth
    jwt_secret: str = "change-me-to-a-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    default_clinic_timezone: str = "Asia/Kolkata"
    cors_origins: list[str] = ["http://localhost:3000"]

    # LangSmith
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "dental-clinic-agent"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
