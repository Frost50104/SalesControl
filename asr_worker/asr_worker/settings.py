"""Application configuration via environment variables."""

from functools import lru_cache

from pydantic import ConfigDict, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """ASR Worker configuration."""

    model_config = ConfigDict(
        env_prefix="",
        case_sensitive=False,
    )

    # Database (connects to core Postgres)
    database_url: str = "postgresql+asyncpg://ingest:ingest@localhost:5432/ingest"

    # Ingest API internal endpoint
    ingest_internal_base_url: str = "http://localhost:8000"
    internal_token: str = ""

    # Temporary audio storage
    audio_tmp_dir: str = "/tmp/asr_worker"

    # Whisper model settings
    whisper_model_fast: str = "base"
    whisper_model_accurate: str = "small"
    whisper_compute_type: str = "int8"
    whisper_threads: int = 8
    whisper_cache_dir: str = "/models"
    beam_size: int = 5
    language: str = "ru"

    # Heuristics for accurate pass
    avg_logprob_threshold: float = -0.7  # Below this triggers accurate pass
    min_text_length_ratio: float = 0.5  # chars per second threshold
    min_duration_for_accurate: float = 15.0  # seconds

    # Worker parameters
    poll_interval_sec: float = 5.0
    batch_size: int = 5  # Smaller batch since ASR is CPU-intensive
    max_retries: int = 3
    retry_delay_sec: float = 2.0

    # Stuck dialogue recovery
    asr_stuck_timeout_sec: float = 600.0  # 10 minutes
    asr_recovery_interval_sec: float = 60.0

    # Metrics
    metrics_log_interval_sec: float = 60.0

    # Logging
    log_level: str = "INFO"

    # HTTP client settings
    http_timeout_sec: float = 60.0

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        """Limit batch size."""
        if v < 1:
            return 1
        if v > 20:
            return 20
        return v

    @field_validator("poll_interval_sec")
    @classmethod
    def validate_poll_interval(cls, v: float) -> float:
        """Ensure reasonable poll interval."""
        if v < 1.0:
            return 1.0
        if v > 300.0:
            return 300.0
        return v


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
