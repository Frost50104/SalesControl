"""Tests for schema validation in openai_client module."""

import pytest
from pydantic import ValidationError

from analysis_worker.openai_client import UpsellAnalysisResult


class TestUpsellAnalysisResult:
    """Tests for UpsellAnalysisResult Pydantic model."""

    def test_valid_complete_result(self):
        """Valid complete result should parse correctly."""
        data = {
            "attempted": "yes",
            "quality_score": 2,
            "categories": ["coffee_size", "dessert"],
            "closing_question": True,
            "customer_reaction": "accepted",
            "evidence_quotes": ["хотите большой?", "добавить десерт?"],
            "summary": "Кассир предложил увеличить размер и добавить десерт.",
            "confidence": 0.85,
        }
        result = UpsellAnalysisResult(**data)
        assert result.attempted == "yes"
        assert result.quality_score == 2
        assert result.categories == ["coffee_size", "dessert"]
        assert result.closing_question is True
        assert result.customer_reaction == "accepted"
        assert len(result.evidence_quotes) == 2
        assert result.confidence == 0.85

    def test_minimal_valid_result(self):
        """Minimal valid result should parse correctly."""
        data = {
            "attempted": "no",
            "quality_score": 0,
            "categories": [],
            "closing_question": False,
            "customer_reaction": "unclear",
            "evidence_quotes": [],
            "summary": "No upsell.",
            "confidence": 0.95,
        }
        result = UpsellAnalysisResult(**data)
        assert result.attempted == "no"
        assert result.quality_score == 0
        assert result.categories == []

    def test_invalid_attempted_value(self):
        """Invalid attempted value should raise ValidationError."""
        data = {
            "attempted": "maybe",  # Invalid
            "quality_score": 1,
            "categories": [],
            "closing_question": False,
            "customer_reaction": "unclear",
            "evidence_quotes": [],
            "summary": "Test",
            "confidence": 0.5,
        }
        with pytest.raises(ValidationError):
            UpsellAnalysisResult(**data)

    def test_quality_score_out_of_range_low(self):
        """Quality score below 0 should raise ValidationError."""
        data = {
            "attempted": "yes",
            "quality_score": -1,  # Invalid
            "categories": [],
            "closing_question": False,
            "customer_reaction": "accepted",
            "evidence_quotes": [],
            "summary": "Test",
            "confidence": 0.5,
        }
        with pytest.raises(ValidationError):
            UpsellAnalysisResult(**data)

    def test_quality_score_out_of_range_high(self):
        """Quality score above 3 should raise ValidationError."""
        data = {
            "attempted": "yes",
            "quality_score": 4,  # Invalid
            "categories": [],
            "closing_question": False,
            "customer_reaction": "accepted",
            "evidence_quotes": [],
            "summary": "Test",
            "confidence": 0.5,
        }
        with pytest.raises(ValidationError):
            UpsellAnalysisResult(**data)

    def test_invalid_category(self):
        """Invalid category should raise ValidationError."""
        data = {
            "attempted": "yes",
            "quality_score": 1,
            "categories": ["invalid_category"],  # Invalid
            "closing_question": False,
            "customer_reaction": "accepted",
            "evidence_quotes": [],
            "summary": "Test",
            "confidence": 0.5,
        }
        with pytest.raises(ValidationError):
            UpsellAnalysisResult(**data)

    def test_invalid_customer_reaction(self):
        """Invalid customer_reaction should raise ValidationError."""
        data = {
            "attempted": "yes",
            "quality_score": 1,
            "categories": [],
            "closing_question": False,
            "customer_reaction": "maybe",  # Invalid
            "evidence_quotes": [],
            "summary": "Test",
            "confidence": 0.5,
        }
        with pytest.raises(ValidationError):
            UpsellAnalysisResult(**data)

    def test_evidence_quotes_truncated(self):
        """Too many evidence quotes should be truncated to 3."""
        data = {
            "attempted": "yes",
            "quality_score": 2,
            "categories": [],
            "closing_question": False,
            "customer_reaction": "accepted",
            "evidence_quotes": ["q1", "q2", "q3", "q4", "q5"],  # 5 quotes
            "summary": "Test",
            "confidence": 0.5,
        }
        result = UpsellAnalysisResult(**data)
        assert len(result.evidence_quotes) == 3

    def test_long_quote_truncated(self):
        """Long quote should be truncated to 100 chars."""
        long_quote = "a" * 200
        data = {
            "attempted": "yes",
            "quality_score": 1,
            "categories": [],
            "closing_question": False,
            "customer_reaction": "accepted",
            "evidence_quotes": [long_quote],
            "summary": "Test",
            "confidence": 0.5,
        }
        result = UpsellAnalysisResult(**data)
        assert len(result.evidence_quotes[0]) == 100

    def test_long_summary_truncated(self):
        """Long summary should be truncated to 200 chars."""
        long_summary = "a" * 300
        data = {
            "attempted": "yes",
            "quality_score": 1,
            "categories": [],
            "closing_question": False,
            "customer_reaction": "accepted",
            "evidence_quotes": [],
            "summary": long_summary,
            "confidence": 0.5,
        }
        result = UpsellAnalysisResult(**data)
        assert len(result.summary) == 200

    def test_confidence_clamped_to_range(self):
        """Confidence outside 0-1 should be clamped."""
        data = {
            "attempted": "yes",
            "quality_score": 1,
            "categories": [],
            "closing_question": False,
            "customer_reaction": "accepted",
            "evidence_quotes": [],
            "summary": "Test",
            "confidence": 1.5,  # Above 1
        }
        result = UpsellAnalysisResult(**data)
        assert result.confidence == 1.0

        data["confidence"] = -0.5  # Below 0
        result = UpsellAnalysisResult(**data)
        assert result.confidence == 0.0

    def test_all_valid_categories(self):
        """All valid categories should be accepted."""
        valid_categories = [
            "coffee_size", "dessert", "pastry", "add_ons",
            "syrup", "combo", "takeaway", "other"
        ]
        data = {
            "attempted": "yes",
            "quality_score": 3,
            "categories": valid_categories,
            "closing_question": True,
            "customer_reaction": "accepted",
            "evidence_quotes": [],
            "summary": "Full upsell",
            "confidence": 1.0,
        }
        result = UpsellAnalysisResult(**data)
        assert result.categories == valid_categories

    def test_all_attempted_values(self):
        """All valid attempted values should be accepted."""
        for attempted in ["yes", "no", "uncertain"]:
            data = {
                "attempted": attempted,
                "quality_score": 1,
                "categories": [],
                "closing_question": False,
                "customer_reaction": "unclear",
                "evidence_quotes": [],
                "summary": "Test",
                "confidence": 0.5,
            }
            result = UpsellAnalysisResult(**data)
            assert result.attempted == attempted

    def test_all_customer_reaction_values(self):
        """All valid customer_reaction values should be accepted."""
        for reaction in ["accepted", "rejected", "unclear"]:
            data = {
                "attempted": "yes",
                "quality_score": 1,
                "categories": [],
                "closing_question": False,
                "customer_reaction": reaction,
                "evidence_quotes": [],
                "summary": "Test",
                "confidence": 0.5,
            }
            result = UpsellAnalysisResult(**data)
            assert result.customer_reaction == reaction
