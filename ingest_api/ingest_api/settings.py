"""Application settings loaded from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration via environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://ingest:ingest@localhost:5432/ingest"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Storage
    audio_storage_dir: str = "/var/lib/ingest_api/audio"

    # Upload limits
    max_upload_size_bytes: int = 10 * 1024 * 1024  # 10 MB

    # Admin token for device management
    admin_token: str = "changeme-admin-token"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # CORS (disabled by default)
    cors_enabled: bool = False
    cors_origins: list[str] = []


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
