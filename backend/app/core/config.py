from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_env: str = "development"
    app_name: str = "AI Shorts Engine Backend"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_shorts_engine"
    sqlalchemy_echo: bool = False
    deployment_language: str = "en"
    auth_mode: str = "development_header"
    default_dev_actor_id: str = "local-dev"
    default_dev_role: str = "admin"
    auth_session_cookie_name: str = "ai_shorts_session"
    auth_session_secret: str | None = None
    auth_session_issuer: str = "ai-shorts-engine"
    auth_session_max_age_seconds: int = 43200
    auth_worker_jwt_secret: str | None = None
    auth_worker_jwt_issuer: str = "ai-shorts-engine-workers"
    auth_worker_required_scope: str = "worker:internal"
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    app_base_url: str = "http://localhost:8000"
    storage_backend: str = "filesystem"
    storage_bucket: str = "ai-shorts-engine"
    local_storage_dir: str = ".data/storage"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    storage_presign_expiry_seconds: int = 3600
    asr_provider_primary: str = "groq"
    asr_provider_fallback: str = "openai"
    groq_api_key: str | None = None
    groq_asr_model: str = "whisper-large-v3-turbo"
    groq_base_url: str = "https://api.groq.com/openai/v1/audio/transcriptions"
    openai_api_key: str | None = None
    openai_asr_model: str = "whisper-1"
    openai_base_url: str = "https://api.openai.com/v1/audio/transcriptions"
    asr_timeout_seconds: int = 120
    asr_max_chunk_seconds: int = 900
    broll_enabled: bool = False
    autoresearch_enabled: bool = False
    outbox_claim_ttl_seconds: int = 300
    outbox_retry_base_seconds: int = 5
    outbox_retry_max_seconds: int = 300
    outbox_max_retries: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
