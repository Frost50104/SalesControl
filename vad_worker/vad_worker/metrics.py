"""Metrics collection and reporting for VAD worker."""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MetricsCollector:
    """Thread-safe metrics collector."""

    # Counters
    chunks_processed: int = 0
    chunks_errors: int = 0
    chunks_requeued: int = 0
    speech_segments_created: int = 0
    dialogues_created: int = 0

    # Timing (in seconds)
    vad_times: list[float] = field(default_factory=list)
    total_processing_times: list[float] = field(default_factory=list)

    # Error tracking
    error_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Window tracking
    window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_chunk_processed(
        self,
        vad_time_sec: float,
        total_time_sec: float,
        segments_count: int,
        dialogues_count: int,
    ) -> None:
        """Record successful chunk processing."""
        with self._lock:
            self.chunks_processed += 1
            self.vad_times.append(vad_time_sec)
            self.total_processing_times.append(total_time_sec)
            self.speech_segments_created += segments_count
            self.dialogues_created += dialogues_count

    def record_chunk_error(self, error_type: str) -> None:
        """Record chunk processing error."""
        with self._lock:
            self.chunks_errors += 1
            self.error_counts[error_type] += 1

    def record_chunks_requeued(self, count: int) -> None:
        """Record stuck chunks requeued."""
        with self._lock:
            self.chunks_requeued += count

    def get_and_reset(self) -> dict[str, Any]:
        """Get current metrics and reset counters."""
        with self._lock:
            now = datetime.now(timezone.utc)
            window_sec = (now - self.window_start).total_seconds()

            # Calculate stats
            avg_vad_time = sum(self.vad_times) / len(self.vad_times) if self.vad_times else 0
            avg_total_time = (
                sum(self.total_processing_times) / len(self.total_processing_times)
                if self.total_processing_times
                else 0
            )
            chunks_per_min = (self.chunks_processed / window_sec * 60) if window_sec > 0 else 0

            result = {
                "window_sec": round(window_sec, 1),
                "chunks_processed": self.chunks_processed,
                "chunks_per_min": round(chunks_per_min, 2),
                "chunks_errors": self.chunks_errors,
                "chunks_requeued": self.chunks_requeued,
                "speech_segments_created": self.speech_segments_created,
                "dialogues_created": self.dialogues_created,
                "avg_vad_time_sec": round(avg_vad_time, 3),
                "avg_total_time_sec": round(avg_total_time, 3),
                "error_breakdown": dict(self.error_counts),
            }

            # Reset
            self.chunks_processed = 0
            self.chunks_errors = 0
            self.chunks_requeued = 0
            self.speech_segments_created = 0
            self.dialogues_created = 0
            self.vad_times.clear()
            self.total_processing_times.clear()
            self.error_counts.clear()
            self.window_start = now

            return result


# Global metrics instance
_metrics: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    """Get or create global metrics collector."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def log_metrics() -> None:
    """Log current metrics and reset."""
    metrics = get_metrics().get_and_reset()

    if metrics["chunks_processed"] == 0 and metrics["chunks_errors"] == 0:
        # No activity - log minimal info
        logger.info(
            "Metrics: idle",
            extra={"metrics": {"status": "idle", "window_sec": metrics["window_sec"]}},
        )
        return

    logger.info(
        "Metrics: %(chunks_processed)d processed, %(chunks_per_min).1f/min, "
        "%(chunks_errors)d errors, avg VAD %(avg_vad_time_sec).3fs",
        metrics,
        extra={"metrics": metrics},
    )

    # Log error breakdown separately if there were errors
    if metrics["error_breakdown"]:
        for error_type, count in metrics["error_breakdown"].items():
            logger.warning(
                f"Error type '{error_type}': {count} occurrences",
                extra={"error_type": error_type, "count": count},
            )


class Timer:
    """Context manager for timing operations."""

    def __init__(self):
        self.start_time: float = 0
        self.elapsed: float = 0

    def __enter__(self) -> "Timer":
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args) -> None:
        self.elapsed = time.perf_counter() - self.start_time
