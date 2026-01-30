"""Tests for ASR heuristics module."""

import os

import pytest

# Set test environment before importing modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["INTERNAL_TOKEN"] = "test-token"

from asr_worker.heuristics import (
    HeuristicsDecision,
    _calculate_garbage_score,
    check_needs_accurate_pass,
)
from asr_worker.transcribe import TranscriptionResult


class TestGarbageScore:
    """Tests for _calculate_garbage_score function."""

    def test_normal_text_low_score(self):
        """Normal Russian text should have low garbage score."""
        text = "Здравствуйте, добрый день. Чем могу помочь?"
        score = _calculate_garbage_score(text)
        assert score < 0.2

    def test_empty_text_zero_score(self):
        """Empty text should return 0."""
        assert _calculate_garbage_score("") == 0.0
        assert _calculate_garbage_score("short") == 0.0

    def test_repeated_chars_high_score(self):
        """Text with many repeated chars should have higher score."""
        text = "ааааааа это тееееест"
        score = _calculate_garbage_score(text)
        assert score > 0.05  # Lower threshold since we average across checks

    def test_repeated_words_high_score(self):
        """Text with many repeated words should have higher score."""
        text = "да да да да да да да да да да"
        score = _calculate_garbage_score(text)
        assert score > 0.2  # Lower threshold since we average across checks

    def test_punctuation_patterns_high_score(self):
        """Text with unusual punctuation should have higher score."""
        text = "что.... это такое???? не понимаю...."
        score = _calculate_garbage_score(text)
        assert score > 0.1


class TestCheckNeedsAccuratePass:
    """Tests for check_needs_accurate_pass function."""

    def test_short_audio_no_accurate_pass(self):
        """Short audio should not trigger accurate pass."""
        result = TranscriptionResult(
            text="Короткий текст",
            segments=[],
            language="ru",
            avg_logprob=-1.5,  # Low confidence
            no_speech_prob=0.1,
            model_name="base",
        )

        decision = check_needs_accurate_pass(result, audio_duration_sec=10.0)

        assert decision.needs_accurate_pass is False

    def test_low_confidence_triggers_accurate_pass(self):
        """Low avg_logprob should trigger accurate pass for long audio."""
        result = TranscriptionResult(
            text="Это достаточно длинный текст для теста",
            segments=[],
            language="ru",
            avg_logprob=-0.9,  # Below default threshold of -0.7
            no_speech_prob=0.1,
            model_name="base",
        )

        decision = check_needs_accurate_pass(result, audio_duration_sec=30.0)

        assert decision.needs_accurate_pass is True
        assert any("confidence" in r.lower() for r in decision.reasons)

    def test_good_confidence_no_accurate_pass(self):
        """Good avg_logprob should not trigger accurate pass."""
        result = TranscriptionResult(
            text="Это достаточно длинный текст для теста с хорошим распознаванием",
            segments=[],
            language="ru",
            avg_logprob=-0.3,  # Above threshold
            no_speech_prob=0.1,
            model_name="base",
        )

        decision = check_needs_accurate_pass(result, audio_duration_sec=30.0)

        assert decision.needs_accurate_pass is False

    def test_short_text_for_duration_triggers_accurate_pass(self):
        """Very short text for long audio should trigger accurate pass."""
        result = TranscriptionResult(
            text="Да",  # Only 2 chars for 30 sec audio
            segments=[],
            language="ru",
            avg_logprob=-0.5,
            no_speech_prob=0.1,
            model_name="base",
        )

        decision = check_needs_accurate_pass(result, audio_duration_sec=30.0)

        assert decision.needs_accurate_pass is True
        assert any("short" in r.lower() for r in decision.reasons)

    def test_high_no_speech_prob_with_text_triggers_accurate_pass(self):
        """High no_speech_prob with text should trigger accurate pass."""
        result = TranscriptionResult(
            text="Это текст который модель не уверена что это речь",
            segments=[],
            language="ru",
            avg_logprob=-0.5,
            no_speech_prob=0.85,  # High no_speech_prob
            model_name="base",
        )

        decision = check_needs_accurate_pass(result, audio_duration_sec=30.0)

        assert decision.needs_accurate_pass is True
        assert any("no_speech" in r.lower() for r in decision.reasons)


class TestHeuristicsDecision:
    """Tests for HeuristicsDecision dataclass."""

    def test_decision_with_reasons(self):
        """HeuristicsDecision should store reasons correctly."""
        decision = HeuristicsDecision(
            needs_accurate_pass=True,
            reasons=["Low confidence: avg_logprob=-0.9", "Text too short"],
        )

        assert decision.needs_accurate_pass is True
        assert len(decision.reasons) == 2

    def test_decision_without_reasons(self):
        """HeuristicsDecision without reasons means fast pass is sufficient."""
        decision = HeuristicsDecision(
            needs_accurate_pass=False,
            reasons=[],
        )

        assert decision.needs_accurate_pass is False
        assert len(decision.reasons) == 0
