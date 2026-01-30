"""Database repository for analysis worker operations."""

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def fetch_pending_dialogues(
    session: AsyncSession,
    batch_size: int,
) -> list[dict[str, Any]]:
    """
    Fetch and lock a batch of dialogues ready for analysis.

    Conditions:
    - asr_status = 'DONE' (transcript available)
    - analysis_status = 'PENDING'
    - has dialogue_transcripts record

    Uses FOR UPDATE SKIP LOCKED to avoid contention.
    """
    query = text("""
        SELECT
            d.dialogue_id, d.device_id, d.point_id, d.register_id,
            d.start_ts, d.end_ts, d.source,
            dt.text as transcript_text,
            dt.language
        FROM dialogues d
        JOIN dialogue_transcripts dt ON d.dialogue_id = dt.dialogue_id
        WHERE d.asr_status = 'DONE'
          AND d.analysis_status = 'PENDING'
        ORDER BY d.start_ts ASC
        LIMIT :batch_size
        FOR UPDATE OF d SKIP LOCKED
    """)
    result = await session.execute(query, {"batch_size": batch_size})
    rows = result.fetchall()
    return [
        {
            "dialogue_id": row.dialogue_id,
            "device_id": row.device_id,
            "point_id": row.point_id,
            "register_id": row.register_id,
            "start_ts": row.start_ts,
            "end_ts": row.end_ts,
            "source": row.source,
            "transcript_text": row.transcript_text,
            "language": row.language,
        }
        for row in rows
    ]


async def update_dialogue_analysis_status(
    session: AsyncSession,
    dialogue_id: UUID,
    status: str,
    error_message: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
) -> None:
    """Update dialogue analysis processing status."""
    now = datetime.now(timezone.utc)

    if status == "PROCESSING":
        query = text("""
            UPDATE dialogues
            SET analysis_status = :status,
                analysis_processing_started_at = :now,
                analysis_started_at = :now
            WHERE dialogue_id = :dialogue_id
        """)
        await session.execute(
            query, {"dialogue_id": dialogue_id, "status": status, "now": now}
        )
    elif status == "DONE":
        query = text("""
            UPDATE dialogues
            SET analysis_status = :status,
                analysis_finished_at = :now,
                analysis_model = :model,
                analysis_prompt_version = :prompt_version,
                analysis_processing_started_at = NULL
            WHERE dialogue_id = :dialogue_id
        """)
        await session.execute(
            query,
            {
                "dialogue_id": dialogue_id,
                "status": status,
                "now": now,
                "model": model,
                "prompt_version": prompt_version,
            },
        )
    elif status == "ERROR":
        query = text("""
            UPDATE dialogues
            SET analysis_status = :status,
                analysis_error_message = :error_message,
                analysis_processing_started_at = NULL
            WHERE dialogue_id = :dialogue_id
        """)
        await session.execute(
            query,
            {
                "dialogue_id": dialogue_id,
                "status": status,
                "error_message": error_message,
            },
        )
    elif status == "SKIPPED":
        query = text("""
            UPDATE dialogues
            SET analysis_status = :status,
                analysis_finished_at = :now,
                analysis_processing_started_at = NULL
            WHERE dialogue_id = :dialogue_id
        """)
        await session.execute(
            query, {"dialogue_id": dialogue_id, "status": status, "now": now}
        )


async def upsert_dialogue_analysis(
    session: AsyncSession,
    dialogue_id: UUID,
    attempted: str,
    quality_score: int,
    categories: list[str],
    closing_question: bool,
    customer_reaction: str,
    evidence_quotes: list[str],
    summary: str,
    confidence: float | None = None,
) -> UUID:
    """
    Insert or update dialogue upsell analysis.
    Uses ON CONFLICT to handle upsert on dialogue_id unique constraint.
    """
    query = text("""
        INSERT INTO dialogue_upsell_analysis
            (dialogue_id, attempted, quality_score, categories, closing_question,
             customer_reaction, evidence_quotes, summary, confidence)
        VALUES
            (:dialogue_id, :attempted, :quality_score, CAST(:categories AS jsonb),
             :closing_question, :customer_reaction, CAST(:evidence_quotes AS jsonb),
             :summary, :confidence)
        ON CONFLICT (dialogue_id) DO UPDATE SET
            attempted = EXCLUDED.attempted,
            quality_score = EXCLUDED.quality_score,
            categories = EXCLUDED.categories,
            closing_question = EXCLUDED.closing_question,
            customer_reaction = EXCLUDED.customer_reaction,
            evidence_quotes = EXCLUDED.evidence_quotes,
            summary = EXCLUDED.summary,
            confidence = EXCLUDED.confidence,
            created_at = now()
        RETURNING analysis_id
    """)
    result = await session.execute(
        query,
        {
            "dialogue_id": dialogue_id,
            "attempted": attempted,
            "quality_score": quality_score,
            "categories": json.dumps(categories),
            "closing_question": closing_question,
            "customer_reaction": customer_reaction,
            "evidence_quotes": json.dumps(evidence_quotes),
            "summary": summary,
            "confidence": confidence,
        },
    )
    analysis_id = result.scalar_one()
    logger.info(
        "Saved upsell analysis",
        extra={
            "dialogue_id": str(dialogue_id),
            "analysis_id": str(analysis_id),
            "attempted": attempted,
            "quality_score": quality_score,
        },
    )
    return analysis_id


async def save_skipped_analysis(
    session: AsyncSession,
    dialogue_id: UUID,
    reason: str,
) -> UUID:
    """
    Save a minimal analysis record for skipped dialogues.
    """
    return await upsert_dialogue_analysis(
        session=session,
        dialogue_id=dialogue_id,
        attempted="uncertain",
        quality_score=0,
        categories=[],
        closing_question=False,
        customer_reaction="unclear",
        evidence_quotes=[],
        summary=f"Skipped: {reason}",
        confidence=None,
    )


async def requeue_stuck_dialogues(
    session: AsyncSession,
    stuck_timeout_sec: float,
) -> int:
    """
    Requeue dialogues stuck in PROCESSING state for longer than timeout.
    Returns count of requeued dialogues.
    """
    query = text("""
        UPDATE dialogues
        SET analysis_status = 'PENDING',
            analysis_processing_started_at = NULL,
            analysis_started_at = NULL
        WHERE analysis_status = 'PROCESSING'
          AND analysis_processing_started_at < NOW() - INTERVAL '1 second' * :timeout_sec
        RETURNING dialogue_id
    """)
    result = await session.execute(query, {"timeout_sec": stuck_timeout_sec})
    rows = result.fetchall()

    if rows:
        dialogue_ids = [str(row.dialogue_id) for row in rows]
        logger.warning(
            f"Requeued {len(rows)} stuck dialogues",
            extra={"requeued_count": len(rows), "dialogue_ids": dialogue_ids[:10]},
        )

    return len(rows)


async def get_dialogue_duration_sec(
    session: AsyncSession,
    dialogue_id: UUID,
) -> float:
    """Calculate dialogue duration from start_ts to end_ts."""
    query = text("""
        SELECT EXTRACT(EPOCH FROM (end_ts - start_ts)) as duration_sec
        FROM dialogues
        WHERE dialogue_id = :dialogue_id
    """)
    result = await session.execute(query, {"dialogue_id": dialogue_id})
    duration = result.scalar_one_or_none()
    return duration if duration else 0.0
