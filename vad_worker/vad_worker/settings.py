"""Application configuration via environment variables."""

from functools import lru_cache

from pydantic import ConfigDict, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """VAD Worker configuration."""

    model_config = ConfigDict(
        env_prefix="",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://ingest:ingest@localhost:5432/ingest"

    # Audio storage
    audio_storage_dir: str = "/data/audio"

    # VAD parameters
    vad_aggressiveness: int = 2  # 0-3, higher = more aggressive filtering
    vad_frame_ms: int = 30  # Frame duration for VAD (10, 20, or 30 ms)

    # Dialogue building
    silence_gap_sec: float = 12.0  # Max silence gap within a dialogue
    max_dialogue_sec: float = 120.0  # Max dialogue duration before splitting

    # Worker parameters
    poll_interval_sec: float = 5.0  # How often to poll for new chunks
    batch_size: int = 10  # How many chunks to process in one batch (1-100)
    max_retries: int = 3  # Max retries for file read errors
    retry_delay_sec: float = 2.0  # Initial delay between retries

    # Stuck chunk recovery
    stuck_timeout_sec: float = 600.0  # 10 minutes - requeue PROCESSING chunks older than this
    recovery_interval_sec: float = 60.0  # How often to check for stuck chunks

    # Metrics
    metrics_log_interval_sec: float = 60.0  # Log metrics every N seconds

    # Logging
    log_level: str = "INFO"

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        """Limit batch size to prevent DB overload."""
        if v < 1:
            return 1
        if v > 100:
            return 100
        return v

    @field_validator("poll_interval_sec")
    @classmethod
    def validate_poll_interval(cls, v: float) -> float:
        """Ensure reasonable poll interval."""
        if v < 1.0:
            return 1.0  # Min 1 second to prevent DB hammering
        if v > 300.0:
            return 300.0  # Max 5 minutes
        return v


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
