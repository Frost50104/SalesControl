"""OpenAI API client with Responses API and structured outputs."""

import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import OpenAI, APIError, RateLimitError, APIConnectionError
from pydantic import BaseModel, ValidationError, field_validator
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .prompt_builder import (
    SYSTEM_PROMPT,
    build_user_prompt,
    get_schema_for_responses_api,
    UPSELL_ANALYSIS_SCHEMA,
)
from .settings import get_settings

logger = logging.getLogger(__name__)


class UpsellAnalysisResult(BaseModel):
    """Pydantic model for validating LLM response."""

    attempted: str
    quality_score: int
    categories: list[str]
    closing_question: bool
    customer_reaction: str
    evidence_quotes: list[str]
    summary: str
    confidence: float

    @field_validator("attempted")
    @classmethod
    def validate_attempted(cls, v: str) -> str:
        if v not in ("yes", "no", "uncertain"):
            raise ValueError(f"Invalid attempted value: {v}")
        return v

    @field_validator("quality_score")
    @classmethod
    def validate_quality_score(cls, v: int) -> int:
        if not (0 <= v <= 3):
            raise ValueError(f"quality_score must be 0-3, got {v}")
        return v

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, v: list[str]) -> list[str]:
        valid = {
            "coffee_size", "dessert", "pastry", "add_ons",
            "syrup", "combo", "takeaway", "other"
        }
        for cat in v:
            if cat not in valid:
                raise ValueError(f"Invalid category: {cat}")
        return v

    @field_validator("customer_reaction")
    @classmethod
    def validate_customer_reaction(cls, v: str) -> str:
        if v not in ("accepted", "rejected", "unclear"):
            raise ValueError(f"Invalid customer_reaction: {v}")
        return v

    @field_validator("evidence_quotes")
    @classmethod
    def validate_evidence_quotes(cls, v: list[str]) -> list[str]:
        if len(v) > 3:
            v = v[:3]
        return [q[:100] for q in v]  # Truncate long quotes

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        return v[:200] if len(v) > 200 else v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


@dataclass
class LLMCallResult:
    """Result of LLM API call."""

    analysis: UpsellAnalysisResult
    model: str
    latency_sec: float
    x_request_id: str | None = None
    fallback_used: bool = False


_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Get or create OpenAI client."""
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY not configured")
        _client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_sec,
        )
    return _client


def _extract_request_id(response: Any) -> str | None:
    """Extract x-request-id from response headers for debugging."""
    try:
        # OpenAI SDK stores headers in _response
        if hasattr(response, "_response") and hasattr(response._response, "headers"):
            return response._response.headers.get("x-request-id")
    except Exception:
        pass
    return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _call_with_structured_output(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[dict[str, Any], str | None]:
    """
    Call OpenAI Responses API with structured output (json_schema).

    Returns (parsed_json, x_request_id).
    """
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        text=get_schema_for_responses_api(),
    )

    x_request_id = _extract_request_id(response)

    # Extract text content from response
    output_text = response.output_text

    try:
        result = json.loads(output_text)
        return result, x_request_id
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse JSON from structured output",
            extra={"error": str(e), "output": output_text[:500]},
        )
        raise ValueError(f"Invalid JSON in response: {e}")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _call_with_json_mode(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> tuple[dict[str, Any], str | None]:
    """
    Fallback: Call OpenAI Chat API with JSON mode (json_object).

    Returns (parsed_json, x_request_id).
    """
    # Add schema to prompt for guidance
    schema_instruction = f"\n\nВерни результат строго в формате JSON по схеме:\n{json.dumps(UPSELL_ANALYSIS_SCHEMA, ensure_ascii=False, indent=2)}"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt + schema_instruction},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    x_request_id = _extract_request_id(response)

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty response from LLM")

    try:
        result = json.loads(content)
        return result, x_request_id
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse JSON from json_mode",
            extra={"error": str(e), "content": content[:500]},
        )
        raise ValueError(f"Invalid JSON in response: {e}")


def analyze_dialogue(
    transcript_text: str,
    duration_sec: float,
    point_id: str,
    register_id: str,
) -> LLMCallResult:
    """
    Analyze dialogue transcript for upsell behavior.

    Uses OpenAI Responses API with structured outputs.
    Falls back to JSON mode if structured outputs fail.

    Returns LLMCallResult with validated analysis.
    """
    import time

    settings = get_settings()
    client = get_client()
    model = settings.openai_model

    user_prompt = build_user_prompt(
        transcript_text=transcript_text,
        duration_sec=duration_sec,
        point_id=point_id,
        register_id=register_id,
    )

    start_time = time.perf_counter()
    fallback_used = False
    x_request_id = None

    try:
        # Try Responses API with structured output first
        raw_result, x_request_id = _call_with_structured_output(
            client=client,
            model=model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except (APIError, ValueError) as e:
        # Check if it's a schema not supported error
        error_msg = str(e).lower()
        if "json_schema" in error_msg or "structured" in error_msg or "format" in error_msg:
            logger.warning(
                f"Structured outputs not supported, falling back to JSON mode: {e}",
                extra={"model": model},
            )
            fallback_used = True
            raw_result, x_request_id = _call_with_json_mode(
                client=client,
                model=model,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        else:
            raise

    latency_sec = time.perf_counter() - start_time

    # Validate with Pydantic
    try:
        analysis = UpsellAnalysisResult(**raw_result)
    except ValidationError as e:
        logger.error(
            "Response validation failed",
            extra={
                "error": str(e),
                "raw_result": raw_result,
                "x_request_id": x_request_id,
            },
        )
        raise ValueError(f"Invalid response structure: {e}")

    logger.info(
        "LLM analysis completed",
        extra={
            "model": model,
            "llm_latency_sec": round(latency_sec, 3),
            "attempted": analysis.attempted,
            "quality_score": analysis.quality_score,
            "x_request_id": x_request_id,
            "fallback_used": fallback_used,
        },
    )

    return LLMCallResult(
        analysis=analysis,
        model=model,
        latency_sec=latency_sec,
        x_request_id=x_request_id,
        fallback_used=fallback_used,
    )
