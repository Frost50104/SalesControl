"""Application configuration via environment variables."""

from functools import lru_cache

from pydantic import ConfigDict, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Analysis Worker configuration."""

    model_config = ConfigDict(
        env_prefix="",
        case_sensitive=False,
    )

    # Database (connects to core Postgres)
    database_url: str = "postgresql+asyncpg://ingest:ingest@localhost:5432/ingest"

    # OpenAI API settings
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_sec: float = 60.0
    openai_max_retries: int = 3
    openai_base_delay_sec: float = 1.0  # Base delay for exponential backoff

    # Prompt versioning
    prompt_version: str = "v1"

    # Prefilter settings
    prefilter_enabled: bool = True
    prefilter_min_text_len: int = 10
    prefilter_min_duration_sec: float = 6.0
    prefilter_upsell_markers: str = (
        "еще,также,может,попробуйте,рекомендую,добавить,большой,средний,"
        "сироп,десерт,выпечка,комбо,с собой,навынос,дополнительно,хотите"
    )

    # Worker parameters
    poll_interval_sec: float = 5.0
    batch_size: int = 10
    max_retries: int = 3
    retry_delay_sec: float = 2.0

    # Stuck dialogue recovery
    analysis_stuck_timeout_sec: float = 600.0  # 10 minutes
    analysis_recovery_interval_sec: float = 60.0

    # Metrics
    metrics_log_interval_sec: float = 60.0

    # Logging
    log_level: str = "INFO"

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        """Limit batch size."""
        if v < 1:
            return 1
        if v > 50:
            return 50
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

    @property
    def upsell_markers_list(self) -> list[str]:
        """Parse upsell markers from comma-separated string."""
        return [m.strip().lower() for m in self.prefilter_upsell_markers.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
