"""Prefilter module for cheap filtering before LLM calls."""

import logging
import re
from dataclasses import dataclass
from typing import Any

from .settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class PrefilterResult:
    """Result of prefilter check."""

    should_skip: bool
    reason: str | None = None


def check_should_skip(
    dialogue: dict[str, Any],
    duration_sec: float,
) -> PrefilterResult:
    """
    Check if dialogue should be skipped (no LLM call needed).

    Reasons to skip:
    1. Prefilter disabled -> never skip
    2. Empty or very short transcript
    3. Very short dialogue duration AND no upsell markers

    Returns PrefilterResult with should_skip flag and reason.
    """
    settings = get_settings()

    if not settings.prefilter_enabled:
        return PrefilterResult(should_skip=False)

    transcript = dialogue.get("transcript_text", "") or ""
    transcript_clean = transcript.strip()

    # Check 1: Empty or very short transcript
    if len(transcript_clean) < settings.prefilter_min_text_len:
        return PrefilterResult(
            should_skip=True,
            reason=f"transcript_too_short ({len(transcript_clean)} chars)",
        )

    # Check 2: Very short duration AND no upsell markers
    if duration_sec < settings.prefilter_min_duration_sec:
        # Check for upsell markers
        transcript_lower = transcript_clean.lower()
        has_markers = any(
            marker in transcript_lower
            for marker in settings.upsell_markers_list
        )

        if not has_markers:
            return PrefilterResult(
                should_skip=True,
                reason=f"short_dialogue_no_markers ({duration_sec:.1f}s)",
            )

    return PrefilterResult(should_skip=False)


def extract_markers_found(text: str) -> list[str]:
    """
    Extract which upsell markers were found in text.
    Useful for debugging/logging.
    """
    settings = get_settings()
    text_lower = text.lower()

    found = []
    for marker in settings.upsell_markers_list:
        if marker in text_lower:
            found.append(marker)

    return found


def estimate_text_complexity(text: str) -> dict[str, Any]:
    """
    Estimate text complexity metrics for logging/debugging.
    """
    words = text.split()
    sentences = re.split(r'[.!?]+', text)

    return {
        "char_count": len(text),
        "word_count": len(words),
        "sentence_count": len([s for s in sentences if s.strip()]),
        "avg_word_length": sum(len(w) for w in words) / len(words) if words else 0,
    }
