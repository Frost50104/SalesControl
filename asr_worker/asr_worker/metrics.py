"""Metrics collection and reporting for ASR worker."""

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
    """Thread-safe metrics collector for ASR worker."""

    # Counters
    dialogues_processed: int = 0
    dialogues_errors: int = 0
    dialogues_requeued: int = 0
    fast_passes: int = 0
    accurate_passes: int = 0

    # Timing (in seconds)
    asr_times: list[float] = field(default_factory=list)
    total_processing_times: list[float] = field(default_factory=list)
    audio_durations: list[float] = field(default_factory=list)

    # Error tracking
    error_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Window tracking
    window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_dialogue_processed(
        self,
        asr_time_sec: float,
        total_time_sec: float,
        audio_duration_sec: float,
        pass_type: str,  # "fast" or "accurate"
    ) -> None:
        """Record successful dialogue processing."""
        with self._lock:
            self.dialogues_processed += 1
            self.asr_times.append(asr_time_sec)
            self.total_processing_times.append(total_time_sec)
            self.audio_durations.append(audio_duration_sec)

            if pass_type == "fast":
                self.fast_passes += 1
            else:
                self.accurate_passes += 1

    def record_dialogue_error(self, error_type: str) -> None:
        """Record dialogue processing error."""
        with self._lock:
            self.dialogues_errors += 1
            self.error_counts[error_type] += 1

    def record_dialogues_requeued(self, count: int) -> None:
        """Record stuck dialogues requeued."""
        with self._lock:
            self.dialogues_requeued += count

    def get_and_reset(self) -> dict[str, Any]:
        """Get current metrics and reset counters."""
        with self._lock:
            now = datetime.now(timezone.utc)
            window_sec = (now - self.window_start).total_seconds()

            # Calculate stats
            avg_asr_time = sum(self.asr_times) / len(self.asr_times) if self.asr_times else 0
            avg_total_time = (
                sum(self.total_processing_times) / len(self.total_processing_times)
                if self.total_processing_times
                else 0
            )
            avg_audio_duration = (
                sum(self.audio_durations) / len(self.audio_durations)
                if self.audio_durations
                else 0
            )

            dialogues_per_min = (
                (self.dialogues_processed / window_sec * 60) if window_sec > 0 else 0
            )

            # RTF: Real-Time Factor (ASR time / audio duration)
            total_asr_time = sum(self.asr_times)
            total_audio_duration = sum(self.audio_durations)
            rtf = total_asr_time / total_audio_duration if total_audio_duration > 0 else 0

            result = {
                "window_sec": round(window_sec, 1),
                "dialogues_processed": self.dialogues_processed,
                "dialogues_per_min": round(dialogues_per_min, 2),
                "dialogues_errors": self.dialogues_errors,
                "dialogues_requeued": self.dialogues_requeued,
                "fast_passes": self.fast_passes,
                "accurate_passes": self.accurate_passes,
                "avg_asr_time_sec": round(avg_asr_time, 3),
                "avg_total_time_sec": round(avg_total_time, 3),
                "avg_audio_duration_sec": round(avg_audio_duration, 2),
                "rtf": round(rtf, 3),  # Real-Time Factor
                "error_breakdown": dict(self.error_counts),
            }

            # Reset
            self.dialogues_processed = 0
            self.dialogues_errors = 0
            self.dialogues_requeued = 0
            self.fast_passes = 0
            self.accurate_passes = 0
            self.asr_times.clear()
            self.total_processing_times.clear()
            self.audio_durations.clear()
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

    if metrics["dialogues_processed"] == 0 and metrics["dialogues_errors"] == 0:
        # No activity - log minimal info
        logger.info(
            "Metrics: idle",
            extra={"metrics": {"status": "idle", "window_sec": metrics["window_sec"]}},
        )
        return

    logger.info(
        "Metrics: %(dialogues_processed)d processed, %(dialogues_per_min).1f/min, "
        "%(dialogues_errors)d errors, RTF %(rtf).3f, avg ASR %(avg_asr_time_sec).3fs",
        metrics,
        extra={"metrics": metrics},
    )

    # Log pass type breakdown
    if metrics["fast_passes"] or metrics["accurate_passes"]:
        logger.info(
            f"Pass breakdown: {metrics['fast_passes']} fast, {metrics['accurate_passes']} accurate",
            extra={
                "fast_passes": metrics["fast_passes"],
                "accurate_passes": metrics["accurate_passes"],
            },
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
