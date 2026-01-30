"""Heuristics for deciding if accurate pass is needed."""

import logging
import re
from dataclasses import dataclass

from .settings import get_settings
from .transcribe import TranscriptionResult

logger = logging.getLogger(__name__)


@dataclass
class HeuristicsDecision:
    """Decision from heuristics analysis."""
    needs_accurate_pass: bool
    reasons: list[str]


def check_needs_accurate_pass(
    result: TranscriptionResult,
    audio_duration_sec: float,
) -> HeuristicsDecision:
    """
    Analyze transcription result and decide if accurate pass is needed.

    Triggers accurate pass if:
    1. avg_logprob is below threshold (low confidence)
    2. Text is suspiciously short for the audio duration
    3. Text contains too many "garbage" patterns (repeated chars, etc.)

    Args:
        result: TranscriptionResult from fast pass
        audio_duration_sec: Total audio duration in seconds

    Returns:
        HeuristicsDecision with decision and reasons
    """
    settings = get_settings()
    reasons = []

    # Skip accurate pass for very short audio
    if audio_duration_sec < settings.min_duration_for_accurate:
        logger.debug(
            "Audio too short for accurate pass consideration",
            extra={"duration_sec": audio_duration_sec},
        )
        return HeuristicsDecision(needs_accurate_pass=False, reasons=[])

    # Check 1: Low confidence (avg_logprob)
    if result.avg_logprob is not None:
        if result.avg_logprob < settings.avg_logprob_threshold:
            reasons.append(
                f"Low confidence: avg_logprob={result.avg_logprob:.3f} < {settings.avg_logprob_threshold}"
            )

    # Check 2: Text too short for audio duration
    text_length = len(result.text)
    expected_min_length = audio_duration_sec * settings.min_text_length_ratio
    if text_length < expected_min_length:
        reasons.append(
            f"Text too short: {text_length} chars for {audio_duration_sec:.1f}s audio "
            f"(expected >= {expected_min_length:.0f})"
        )

    # Check 3: Garbage patterns in text
    garbage_score = _calculate_garbage_score(result.text)
    if garbage_score > 0.3:  # More than 30% garbage
        reasons.append(f"High garbage score: {garbage_score:.2f}")

    # Check 4: High no_speech_prob but we got text
    if result.no_speech_prob is not None and result.no_speech_prob > 0.7 and text_length > 10:
        reasons.append(
            f"High no_speech_prob ({result.no_speech_prob:.2f}) but text present"
        )

    needs_accurate = len(reasons) > 0

    if needs_accurate:
        logger.info(
            "Accurate pass triggered",
            extra={
                "reasons": reasons,
                "avg_logprob": result.avg_logprob,
                "text_length": text_length,
                "audio_duration_sec": audio_duration_sec,
            },
        )
    else:
        logger.debug("Fast pass sufficient, no accurate pass needed")

    return HeuristicsDecision(
        needs_accurate_pass=needs_accurate,
        reasons=reasons,
    )


def _calculate_garbage_score(text: str) -> float:
    """
    Calculate a "garbage" score for the text.
    Higher score means more likely to be garbage transcription.

    Checks for:
    - Repeated characters (aaaaa, ........)
    - Repeated words
    - Unusual punctuation patterns
    - Very long "words" without spaces
    """
    if not text or len(text) < 10:
        return 0.0

    total_score = 0.0
    total_checks = 4

    # Check 1: Repeated characters (3+ same char in a row)
    repeated_chars = re.findall(r'(.)\1{2,}', text)
    repeated_ratio = sum(len(m) for m in repeated_chars) / len(text) if text else 0
    total_score += min(repeated_ratio * 3, 1.0)  # Scale up, cap at 1

    # Check 2: Repeated words
    words = text.lower().split()
    if len(words) > 3:
        unique_words = set(words)
        repetition_ratio = 1 - (len(unique_words) / len(words))
        # Only penalize if repetition is extreme
        if repetition_ratio > 0.5:
            total_score += repetition_ratio

    # Check 3: Unusual punctuation (many . or ? in a row)
    punct_patterns = re.findall(r'[.?!]{3,}', text)
    punct_score = len(punct_patterns) * 0.2
    total_score += min(punct_score, 1.0)

    # Check 4: Very long "words" (might be merged garbage)
    long_words = [w for w in words if len(w) > 30]
    long_word_score = len(long_words) * 0.3
    total_score += min(long_word_score, 1.0)

    return total_score / total_checks


def analyze_transcription_quality(result: TranscriptionResult) -> dict:
    """
    Analyze transcription quality for logging/monitoring.
    Returns quality metrics.
    """
    text = result.text
    words = text.split() if text else []

    return {
        "text_length": len(text),
        "word_count": len(words),
        "segments_count": len(result.segments),
        "avg_logprob": result.avg_logprob,
        "no_speech_prob": result.no_speech_prob,
        "garbage_score": _calculate_garbage_score(text),
        "avg_word_length": sum(len(w) for w in words) / len(words) if words else 0,
    }
