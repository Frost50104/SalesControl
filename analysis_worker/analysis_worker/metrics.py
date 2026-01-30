"""Metrics collection and reporting for analysis worker."""

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
    """Thread-safe metrics collector for analysis worker."""

    # Counters
    dialogues_processed: int = 0
    dialogues_errors: int = 0
    dialogues_skipped: int = 0
    dialogues_requeued: int = 0
    llm_calls: int = 0
    fallback_calls: int = 0

    # Timing (in seconds)
    llm_latencies: list[float] = field(default_factory=list)
    total_processing_times: list[float] = field(default_factory=list)

    # Quality distribution
    quality_scores: list[int] = field(default_factory=list)
    attempted_counts: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )

    # Error tracking
    error_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    skip_reasons: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Window tracking
    window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_dialogue_processed(
        self,
        llm_latency_sec: float,
        total_time_sec: float,
        attempted: str,
        quality_score: int,
        fallback_used: bool = False,
    ) -> None:
        """Record successful dialogue processing."""
        with self._lock:
            self.dialogues_processed += 1
            self.llm_calls += 1
            self.llm_latencies.append(llm_latency_sec)
            self.total_processing_times.append(total_time_sec)
            self.quality_scores.append(quality_score)
            self.attempted_counts[attempted] += 1
            if fallback_used:
                self.fallback_calls += 1

    def record_dialogue_skipped(self, reason: str) -> None:
        """Record skipped dialogue."""
        with self._lock:
            self.dialogues_skipped += 1
            self.skip_reasons[reason] += 1

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
            avg_llm_latency = (
                sum(self.llm_latencies) / len(self.llm_latencies)
                if self.llm_latencies else 0
            )
            avg_total_time = (
                sum(self.total_processing_times) / len(self.total_processing_times)
                if self.total_processing_times else 0
            )
            avg_quality = (
                sum(self.quality_scores) / len(self.quality_scores)
                if self.quality_scores else 0
            )

            processed_per_min = (
                (self.dialogues_processed / window_sec * 60) if window_sec > 0 else 0
            )

            result = {
                "window_sec": round(window_sec, 1),
                "dialogues_processed": self.dialogues_processed,
                "processed_per_min": round(processed_per_min, 2),
                "dialogues_skipped": self.dialogues_skipped,
                "dialogues_errors": self.dialogues_errors,
                "dialogues_requeued": self.dialogues_requeued,
                "llm_calls": self.llm_calls,
                "fallback_calls": self.fallback_calls,
                "avg_llm_latency_sec": round(avg_llm_latency, 3),
                "avg_total_time_sec": round(avg_total_time, 3),
                "avg_quality_score": round(avg_quality, 2),
                "attempted_breakdown": dict(self.attempted_counts),
                "error_breakdown": dict(self.error_counts),
                "skip_breakdown": dict(self.skip_reasons),
            }

            # Reset
            self.dialogues_processed = 0
            self.dialogues_errors = 0
            self.dialogues_skipped = 0
            self.dialogues_requeued = 0
            self.llm_calls = 0
            self.fallback_calls = 0
            self.llm_latencies.clear()
            self.total_processing_times.clear()
            self.quality_scores.clear()
            self.attempted_counts.clear()
            self.error_counts.clear()
            self.skip_reasons.clear()
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

    total_activity = (
        metrics["dialogues_processed"]
        + metrics["dialogues_skipped"]
        + metrics["dialogues_errors"]
    )

    if total_activity == 0:
        # No activity - log minimal info
        logger.info(
            "Metrics: idle",
            extra={"metrics": {"status": "idle", "window_sec": metrics["window_sec"]}},
        )
        return

    logger.info(
        "Metrics: %(dialogues_processed)d processed, %(processed_per_min).1f/min, "
        "%(dialogues_skipped)d skipped, %(dialogues_errors)d errors, "
        "avg LLM %(avg_llm_latency_sec).3fs, avg quality %(avg_quality_score).2f",
        metrics,
        extra={"metrics": metrics},
    )

    # Log attempted breakdown
    if metrics["attempted_breakdown"]:
        attempted_str = ", ".join(
            f"{k}={v}" for k, v in metrics["attempted_breakdown"].items()
        )
        logger.info(
            f"Attempted breakdown: {attempted_str}",
            extra={"attempted_breakdown": metrics["attempted_breakdown"]},
        )

    # Log error breakdown separately if there were errors
    if metrics["error_breakdown"]:
        for error_type, count in metrics["error_breakdown"].items():
            logger.warning(
                f"Error type '{error_type}': {count} occurrences",
                extra={"error_type": error_type, "count": count},
            )

    # Log skip reasons
    if metrics["skip_breakdown"]:
        for reason, count in metrics["skip_breakdown"].items():
            logger.info(
                f"Skip reason '{reason}': {count}",
                extra={"skip_reason": reason, "count": count},
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
