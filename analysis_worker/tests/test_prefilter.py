"""Tests for prefilter module."""

import pytest
from unittest.mock import patch

from analysis_worker.prefilter import (
    check_should_skip,
    extract_markers_found,
    estimate_text_complexity,
)


class TestCheckShouldSkip:
    """Tests for check_should_skip function."""

    def test_empty_transcript_should_skip(self):
        """Empty transcript should be skipped."""
        dialogue = {"transcript_text": ""}
        result = check_should_skip(dialogue, duration_sec=30.0)
        assert result.should_skip is True
        assert "transcript_too_short" in result.reason

    def test_whitespace_transcript_should_skip(self):
        """Whitespace-only transcript should be skipped."""
        dialogue = {"transcript_text": "   \n\t  "}
        result = check_should_skip(dialogue, duration_sec=30.0)
        assert result.should_skip is True
        assert "transcript_too_short" in result.reason

    def test_very_short_transcript_should_skip(self):
        """Very short transcript (< min_len) should be skipped."""
        dialogue = {"transcript_text": "Привет"}  # 6 chars
        result = check_should_skip(dialogue, duration_sec=30.0)
        assert result.should_skip is True

    def test_normal_transcript_should_not_skip(self):
        """Normal transcript should not be skipped."""
        dialogue = {
            "transcript_text": "Здравствуйте, мне большой латте пожалуйста"
        }
        result = check_should_skip(dialogue, duration_sec=30.0)
        assert result.should_skip is False

    def test_short_dialogue_no_markers_should_skip(self):
        """Short dialogue without upsell markers should be skipped."""
        dialogue = {
            "transcript_text": "Один чай спасибо"  # No upsell markers
        }
        result = check_should_skip(dialogue, duration_sec=3.0)  # Very short
        assert result.should_skip is True
        assert "short_dialogue_no_markers" in result.reason

    def test_short_dialogue_with_markers_should_not_skip(self):
        """Short dialogue WITH upsell markers should NOT be skipped."""
        dialogue = {
            "transcript_text": "Хотите еще что-нибудь добавить?"  # Has markers
        }
        result = check_should_skip(dialogue, duration_sec=3.0)
        assert result.should_skip is False

    def test_prefilter_disabled(self):
        """When prefilter is disabled, nothing should be skipped."""
        with patch("analysis_worker.prefilter.get_settings") as mock_settings:
            mock_settings.return_value.prefilter_enabled = False
            dialogue = {"transcript_text": ""}
            result = check_should_skip(dialogue, duration_sec=1.0)
            assert result.should_skip is False

    def test_none_transcript_should_skip(self):
        """None transcript should be handled gracefully."""
        dialogue = {"transcript_text": None}
        result = check_should_skip(dialogue, duration_sec=30.0)
        assert result.should_skip is True

    def test_missing_transcript_key_should_skip(self):
        """Missing transcript key should be handled gracefully."""
        dialogue = {}
        result = check_should_skip(dialogue, duration_sec=30.0)
        assert result.should_skip is True


class TestExtractMarkersFound:
    """Tests for extract_markers_found function."""

    def test_no_markers(self):
        """Text without markers should return empty list."""
        result = extract_markers_found("Один американо спасибо")
        assert result == []

    def test_single_marker(self):
        """Text with one marker should return it."""
        result = extract_markers_found("Хотите что-нибудь еще?")
        assert "еще" in result or "хотите" in result

    def test_multiple_markers(self):
        """Text with multiple markers should return all."""
        result = extract_markers_found("Хотите также попробовать десерт?")
        assert len(result) >= 2

    def test_case_insensitive(self):
        """Marker detection should be case-insensitive."""
        result = extract_markers_found("ХОТИТЕ ЕЩЕ?")
        assert len(result) >= 1


class TestEstimateTextComplexity:
    """Tests for estimate_text_complexity function."""

    def test_empty_text(self):
        """Empty text should return zeros."""
        result = estimate_text_complexity("")
        assert result["char_count"] == 0
        assert result["word_count"] == 0

    def test_simple_text(self):
        """Simple text should return correct counts."""
        result = estimate_text_complexity("Один два три")
        assert result["char_count"] == 12
        assert result["word_count"] == 3

    def test_multisentence_text(self):
        """Multi-sentence text should count sentences."""
        result = estimate_text_complexity("Привет. Как дела? Хорошо!")
        assert result["sentence_count"] == 3
