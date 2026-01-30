"""Prompt builder for upsell analysis LLM calls."""

from typing import Any

# JSON Schema for structured output (OpenAI Responses API)
UPSELL_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "attempted": {
            "type": "string",
            "enum": ["yes", "no", "uncertain"],
            "description": "Was an upsell attempt made by the cashier?"
        },
        "quality_score": {
            "type": "integer",
            "minimum": 0,
            "maximum": 3,
            "description": "Quality of upsell attempt: 0=none/bad, 1=minimal, 2=good, 3=excellent"
        },
        "categories": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "coffee_size",
                    "dessert",
                    "pastry",
                    "add_ons",
                    "syrup",
                    "combo",
                    "takeaway",
                    "other"
                ]
            },
            "description": "Categories of products offered in upsell"
        },
        "closing_question": {
            "type": "boolean",
            "description": "Did cashier ask a closing question (e.g., 'Anything else?')?"
        },
        "customer_reaction": {
            "type": "string",
            "enum": ["accepted", "rejected", "unclear"],
            "description": "How did the customer respond to the upsell?"
        },
        "evidence_quotes": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 100
            },
            "minItems": 0,
            "maxItems": 3,
            "description": "1-3 short quotes (<=12 words each) from transcript as evidence"
        },
        "summary": {
            "type": "string",
            "maxLength": 200,
            "description": "Brief 1-2 sentence explanation of the analysis"
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence in analysis (0-1)"
        }
    },
    "required": [
        "attempted",
        "quality_score",
        "categories",
        "closing_question",
        "customer_reaction",
        "evidence_quotes",
        "summary",
        "confidence"
    ],
    "additionalProperties": False
}


SYSTEM_PROMPT = """Ты — эксперт по анализу качества обслуживания в сфере фастфуда/кофеен.
Твоя задача — определить, предлагал ли кассир дополнительные товары (допродажу/upsell) и оценить качество предложения.

ПРАВИЛА ОЦЕНКИ:

1. attempted (попытка допродажи):
   - "yes" — кассир явно предложил что-то дополнительное
   - "no" — кассир НЕ предлагал ничего дополнительного
   - "uncertain" — неясно из текста, используй при сомнениях

2. quality_score (0-3):
   - 0: Нет предложения или откровенно плохое
   - 1: Минимальное усилие (просто "что-то еще?")
   - 2: Хорошее предложение (конкретный товар)
   - 3: Отличное (персонализированное, с обоснованием)

3. categories — выбери применимые:
   - coffee_size: увеличение размера напитка
   - dessert: десерты
   - pastry: выпечка
   - add_ons: добавки общие
   - syrup: сиропы
   - combo: комбо-наборы
   - takeaway: предложение с собой
   - other: прочее

4. closing_question: был ли "закрывающий вопрос" типа "Это всё?", "Что-нибудь ещё?"

5. customer_reaction:
   - "accepted" — клиент согласился
   - "rejected" — клиент отказался
   - "unclear" — реакция неясна

6. evidence_quotes: 1-3 ТОЧНЫЕ цитаты из текста (не более 12 слов каждая)
   ВАЖНО: цитируй только то, что РЕАЛЬНО есть в тексте!

7. summary: 1-2 предложения объяснения

8. confidence: уверенность в анализе (0.0-1.0)

ВАЖНО:
- Не придумывай то, чего нет в тексте
- Если сомневаешься — ставь attempted="uncertain"
- Цитаты должны быть ТОЧНЫМИ из входного текста"""


def build_user_prompt(
    transcript_text: str,
    duration_sec: float,
    point_id: str,
    register_id: str,
) -> str:
    """Build user prompt with transcript and context."""
    return f"""Проанализируй следующий диалог кассира с клиентом:

=== ТРАНСКРИПТ ===
{transcript_text}
=== КОНЕЦ ТРАНСКРИПТА ===

Контекст:
- Длительность диалога: {duration_sec:.1f} секунд
- Точка: {point_id}
- Касса: {register_id}

Определи:
1. Была ли попытка допродажи?
2. Оцени качество (0-3)
3. Какие категории товаров предлагались?
4. Был ли закрывающий вопрос?
5. Как отреагировал клиент?
6. Приведи цитаты-доказательства из текста
7. Кратко объясни свой анализ

Отвечай ТОЛЬКО валидным JSON по указанной схеме."""


def get_schema_for_responses_api() -> dict[str, Any]:
    """
    Get schema formatted for OpenAI Responses API.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "upsell_eval",
            "strict": True,
            "schema": UPSELL_ANALYSIS_SCHEMA,
        }
    }


def get_schema_for_json_mode() -> dict[str, Any]:
    """
    Get schema description for JSON mode fallback (older models).
    Returns schema to include in prompt for validation.
    """
    return UPSELL_ANALYSIS_SCHEMA
