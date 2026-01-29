"""Database repository for VAD worker operations."""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def fetch_queued_chunks(
    session: AsyncSession,
    batch_size: int,
) -> list[dict[str, Any]]:
    """
    Fetch and lock a batch of QUEUED chunks for processing.
    Uses FOR UPDATE SKIP LOCKED to avoid contention.
    """
    query = text("""
        SELECT
            chunk_id, device_id, point_id, register_id,
            start_ts, end_ts, duration_sec,
            sample_rate, channels, file_path
        FROM audio_chunks
        WHERE status = 'QUEUED'
        ORDER BY start_ts ASC
        LIMIT :batch_size
        FOR UPDATE SKIP LOCKED
    """)
    result = await session.execute(query, {"batch_size": batch_size})
    rows = result.fetchall()
    return [
        {
            "chunk_id": row.chunk_id,
            "device_id": row.device_id,
            "point_id": row.point_id,
            "register_id": row.register_id,
            "start_ts": row.start_ts,
            "end_ts": row.end_ts,
            "duration_sec": row.duration_sec,
            "sample_rate": row.sample_rate,
            "channels": row.channels,
            "file_path": row.file_path,
        }
        for row in rows
    ]


async def update_chunk_status(
    session: AsyncSession,
    chunk_id: UUID,
    status: str,
    error_message: str | None = None,
) -> None:
    """Update chunk processing status."""
    now = datetime.now(timezone.utc)

    if status == "PROCESSING":
        # Set processing_started_at when entering PROCESSING
        query = text("""
            UPDATE audio_chunks
            SET status = :status, processing_started_at = :now
            WHERE chunk_id = :chunk_id
        """)
        await session.execute(
            query, {"chunk_id": chunk_id, "status": status, "now": now}
        )
    elif error_message:
        # Clear processing_started_at on terminal states
        query = text("""
            UPDATE audio_chunks
            SET status = :status, error_message = :error_message, processing_started_at = NULL
            WHERE chunk_id = :chunk_id
        """)
        await session.execute(
            query,
            {"chunk_id": chunk_id, "status": status, "error_message": error_message},
        )
    else:
        # Clear processing_started_at on terminal states
        query = text("""
            UPDATE audio_chunks
            SET status = :status, processing_started_at = NULL
            WHERE chunk_id = :chunk_id
        """)
        await session.execute(query, {"chunk_id": chunk_id, "status": status})


async def requeue_stuck_chunks(
    session: AsyncSession,
    stuck_timeout_sec: float,
) -> int:
    """
    Requeue chunks stuck in PROCESSING state for longer than timeout.
    Returns count of requeued chunks.
    """
    query = text("""
        UPDATE audio_chunks
        SET status = 'QUEUED', processing_started_at = NULL
        WHERE status = 'PROCESSING'
          AND processing_started_at < NOW() - INTERVAL '1 second' * :timeout_sec
        RETURNING chunk_id
    """)
    result = await session.execute(query, {"timeout_sec": stuck_timeout_sec})
    rows = result.fetchall()

    if rows:
        chunk_ids = [str(row.chunk_id) for row in rows]
        logger.warning(
            f"Requeued {len(rows)} stuck chunks",
            extra={"requeued_count": len(rows), "chunk_ids": chunk_ids[:10]},
        )

    return len(rows)


async def save_speech_segments(
    session: AsyncSession,
    chunk_id: UUID,
    segments: list[tuple[int, int]],
) -> list[UUID]:
    """
    Save speech segments to database.
    Returns list of created segment IDs.
    """
    if not segments:
        return []

    segment_ids = []
    for start_ms, end_ms in segments:
        query = text("""
            INSERT INTO speech_segments (chunk_id, start_ms, end_ms)
            VALUES (:chunk_id, :start_ms, :end_ms)
            RETURNING id
        """)
        result = await session.execute(
            query,
            {"chunk_id": chunk_id, "start_ms": start_ms, "end_ms": end_ms},
        )
        segment_id = result.scalar_one()
        segment_ids.append(segment_id)

    logger.info(
        "Saved speech segments",
        extra={"chunk_id": str(chunk_id), "count": len(segments)},
    )
    return segment_ids


async def get_device_dialogue_state(
    session: AsyncSession,
    device_id: UUID,
) -> dict[str, Any] | None:
    """Get current dialogue state for a device."""
    query = text("""
        SELECT device_id, open_dialogue_id, last_speech_end_ts, updated_at
        FROM device_dialogue_state
        WHERE device_id = :device_id
        FOR UPDATE
    """)
    result = await session.execute(query, {"device_id": device_id})
    row = result.fetchone()
    if row is None:
        return None
    return {
        "device_id": row.device_id,
        "open_dialogue_id": row.open_dialogue_id,
        "last_speech_end_ts": row.last_speech_end_ts,
        "updated_at": row.updated_at,
    }


async def upsert_device_dialogue_state(
    session: AsyncSession,
    device_id: UUID,
    open_dialogue_id: UUID | None,
    last_speech_end_ts: datetime | None,
) -> None:
    """Insert or update device dialogue state."""
    query = text("""
        INSERT INTO device_dialogue_state (device_id, open_dialogue_id, last_speech_end_ts, updated_at)
        VALUES (:device_id, :open_dialogue_id, :last_speech_end_ts, :updated_at)
        ON CONFLICT (device_id) DO UPDATE SET
            open_dialogue_id = EXCLUDED.open_dialogue_id,
            last_speech_end_ts = EXCLUDED.last_speech_end_ts,
            updated_at = EXCLUDED.updated_at
    """)
    await session.execute(
        query,
        {
            "device_id": device_id,
            "open_dialogue_id": open_dialogue_id,
            "last_speech_end_ts": last_speech_end_ts,
            "updated_at": datetime.now(timezone.utc),
        },
    )


async def create_dialogue(
    session: AsyncSession,
    device_id: UUID,
    point_id: UUID,
    register_id: UUID,
    start_ts: datetime,
    end_ts: datetime,
    source: str = "vad",
) -> UUID:
    """Create a new dialogue and return its ID."""
    query = text("""
        INSERT INTO dialogues (device_id, point_id, register_id, start_ts, end_ts, source)
        VALUES (:device_id, :point_id, :register_id, :start_ts, :end_ts, :source)
        RETURNING dialogue_id
    """)
    result = await session.execute(
        query,
        {
            "device_id": device_id,
            "point_id": point_id,
            "register_id": register_id,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "source": source,
        },
    )
    dialogue_id = result.scalar_one()
    logger.info(
        "Created dialogue",
        extra={"dialogue_id": str(dialogue_id), "device_id": str(device_id)},
    )
    return dialogue_id


async def update_dialogue_end_ts(
    session: AsyncSession,
    dialogue_id: UUID,
    end_ts: datetime,
) -> None:
    """Update the end timestamp of an existing dialogue."""
    query = text("""
        UPDATE dialogues
        SET end_ts = :end_ts
        WHERE dialogue_id = :dialogue_id
    """)
    await session.execute(query, {"dialogue_id": dialogue_id, "end_ts": end_ts})


async def add_dialogue_segment(
    session: AsyncSession,
    dialogue_id: UUID,
    chunk_id: UUID,
    start_ms: int,
    end_ms: int,
) -> None:
    """Add a segment to a dialogue."""
    query = text("""
        INSERT INTO dialogue_segments (dialogue_id, chunk_id, start_ms, end_ms)
        VALUES (:dialogue_id, :chunk_id, :start_ms, :end_ms)
        ON CONFLICT DO NOTHING
    """)
    await session.execute(
        query,
        {
            "dialogue_id": dialogue_id,
            "chunk_id": chunk_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
        },
    )


async def get_dialogue_by_id(
    session: AsyncSession,
    dialogue_id: UUID,
) -> dict[str, Any] | None:
    """Get dialogue by ID."""
    query = text("""
        SELECT dialogue_id, device_id, point_id, register_id, start_ts, end_ts, source, created_at
        FROM dialogues
        WHERE dialogue_id = :dialogue_id
    """)
    result = await session.execute(query, {"dialogue_id": dialogue_id})
    row = result.fetchone()
    if row is None:
        return None
    return {
        "dialogue_id": row.dialogue_id,
        "device_id": row.device_id,
        "point_id": row.point_id,
        "register_id": row.register_id,
        "start_ts": row.start_ts,
        "end_ts": row.end_ts,
        "source": row.source,
        "created_at": row.created_at,
    }
