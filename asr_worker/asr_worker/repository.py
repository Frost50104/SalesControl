"""Database repository for ASR worker operations."""

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
    Fetch and lock a batch of PENDING dialogues for ASR processing.
    Uses FOR UPDATE SKIP LOCKED to avoid contention.
    """
    query = text("""
        SELECT
            dialogue_id, device_id, point_id, register_id,
            start_ts, end_ts, source
        FROM dialogues
        WHERE asr_status = 'PENDING'
        ORDER BY start_ts ASC
        LIMIT :batch_size
        FOR UPDATE SKIP LOCKED
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
        }
        for row in rows
    ]


async def update_dialogue_asr_status(
    session: AsyncSession,
    dialogue_id: UUID,
    status: str,
    error_message: str | None = None,
    asr_pass: str | None = None,
    asr_model: str | None = None,
) -> None:
    """Update dialogue ASR processing status."""
    now = datetime.now(timezone.utc)

    if status == "PROCESSING":
        query = text("""
            UPDATE dialogues
            SET asr_status = :status,
                asr_processing_started_at = :now,
                asr_started_at = :now
            WHERE dialogue_id = :dialogue_id
        """)
        await session.execute(
            query, {"dialogue_id": dialogue_id, "status": status, "now": now}
        )
    elif status == "DONE":
        query = text("""
            UPDATE dialogues
            SET asr_status = :status,
                asr_finished_at = :now,
                asr_pass = :asr_pass,
                asr_model = :asr_model,
                asr_processing_started_at = NULL
            WHERE dialogue_id = :dialogue_id
        """)
        await session.execute(
            query,
            {
                "dialogue_id": dialogue_id,
                "status": status,
                "now": now,
                "asr_pass": asr_pass,
                "asr_model": asr_model,
            },
        )
    elif status == "ERROR":
        query = text("""
            UPDATE dialogues
            SET asr_status = :status,
                asr_error_message = :error_message,
                asr_processing_started_at = NULL
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


async def get_dialogue_segments(
    session: AsyncSession,
    dialogue_id: UUID,
) -> list[dict[str, Any]]:
    """
    Get all segments for a dialogue, ordered by chunk start time and segment start.
    Includes chunk file_path for fetching audio.
    """
    query = text("""
        SELECT
            ds.chunk_id,
            ds.start_ms,
            ds.end_ms,
            ac.file_path,
            ac.start_ts as chunk_start_ts,
            ac.sample_rate,
            ac.channels
        FROM dialogue_segments ds
        JOIN audio_chunks ac ON ds.chunk_id = ac.chunk_id
        WHERE ds.dialogue_id = :dialogue_id
        ORDER BY ac.start_ts ASC, ds.start_ms ASC
    """)
    result = await session.execute(query, {"dialogue_id": dialogue_id})
    rows = result.fetchall()
    return [
        {
            "chunk_id": row.chunk_id,
            "start_ms": row.start_ms,
            "end_ms": row.end_ms,
            "file_path": row.file_path,
            "chunk_start_ts": row.chunk_start_ts,
            "sample_rate": row.sample_rate,
            "channels": row.channels,
        }
        for row in rows
    ]


async def upsert_dialogue_transcript(
    session: AsyncSession,
    dialogue_id: UUID,
    language: str,
    text_content: str,
    segments_json: list[dict[str, Any]] | None,
    avg_logprob: float | None,
    no_speech_prob: float | None,
) -> UUID:
    """
    Insert or update dialogue transcript.
    Uses ON CONFLICT to handle upsert on dialogue_id unique constraint.
    """
    query = text("""
        INSERT INTO dialogue_transcripts
            (dialogue_id, language, text, segments_json, avg_logprob, no_speech_prob)
        VALUES
            (:dialogue_id, :language, :text, :segments_json::jsonb, :avg_logprob, :no_speech_prob)
        ON CONFLICT (dialogue_id) DO UPDATE SET
            language = EXCLUDED.language,
            text = EXCLUDED.text,
            segments_json = EXCLUDED.segments_json,
            avg_logprob = EXCLUDED.avg_logprob,
            no_speech_prob = EXCLUDED.no_speech_prob,
            created_at = now()
        RETURNING transcript_id
    """)
    import json
    result = await session.execute(
        query,
        {
            "dialogue_id": dialogue_id,
            "language": language,
            "text": text_content,
            "segments_json": json.dumps(segments_json) if segments_json else None,
            "avg_logprob": avg_logprob,
            "no_speech_prob": no_speech_prob,
        },
    )
    transcript_id = result.scalar_one()
    logger.info(
        "Saved transcript",
        extra={
            "dialogue_id": str(dialogue_id),
            "transcript_id": str(transcript_id),
            "text_length": len(text_content),
        },
    )
    return transcript_id


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
        SET asr_status = 'PENDING',
            asr_processing_started_at = NULL,
            asr_started_at = NULL
        WHERE asr_status = 'PROCESSING'
          AND asr_processing_started_at < NOW() - INTERVAL '1 second' * :timeout_sec
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
    """Calculate total audio duration for a dialogue in seconds."""
    query = text("""
        SELECT COALESCE(SUM(ds.end_ms - ds.start_ms), 0) as total_ms
        FROM dialogue_segments ds
        WHERE ds.dialogue_id = :dialogue_id
    """)
    result = await session.execute(query, {"dialogue_id": dialogue_id})
    total_ms = result.scalar_one()
    return total_ms / 1000.0 if total_ms else 0.0
