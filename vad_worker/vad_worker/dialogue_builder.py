"""Dialogue builder - combines speech segments into dialogues."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from . import repository
from .settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class SegmentInfo:
    """Speech segment with absolute timestamps."""

    chunk_id: UUID
    start_ms: int  # Relative to chunk start
    end_ms: int  # Relative to chunk start
    abs_start: datetime  # Absolute timestamp
    abs_end: datetime  # Absolute timestamp


@dataclass
class DialogueInfo:
    """Information about a dialogue being built."""

    dialogue_id: UUID | None  # None if not yet persisted
    device_id: UUID
    point_id: UUID
    register_id: UUID
    start_ts: datetime
    end_ts: datetime
    segments: list[SegmentInfo] = field(default_factory=list)


def segments_to_absolute(
    chunk_id: UUID,
    chunk_start_ts: datetime,
    segments: list[tuple[int, int]],
) -> list[SegmentInfo]:
    """Convert relative segment timestamps to absolute."""
    result = []
    for start_ms, end_ms in segments:
        abs_start = chunk_start_ts + timedelta(milliseconds=start_ms)
        abs_end = chunk_start_ts + timedelta(milliseconds=end_ms)
        result.append(
            SegmentInfo(
                chunk_id=chunk_id,
                start_ms=start_ms,
                end_ms=end_ms,
                abs_start=abs_start,
                abs_end=abs_end,
            )
        )
    return result


def build_dialogues_from_segments(
    segments: list[SegmentInfo],
    silence_gap_sec: float,
    max_dialogue_sec: float,
) -> list[list[SegmentInfo]]:
    """
    Group segments into dialogues based on silence gaps and max duration.

    Args:
        segments: List of SegmentInfo with absolute timestamps
        silence_gap_sec: Max silence between segments to keep them in same dialogue
        max_dialogue_sec: Max dialogue duration before splitting

    Returns:
        List of dialogue segment groups
    """
    if not segments:
        return []

    silence_gap = timedelta(seconds=silence_gap_sec)
    max_duration = timedelta(seconds=max_dialogue_sec)

    dialogues: list[list[SegmentInfo]] = []
    current_dialogue: list[SegmentInfo] = []
    dialogue_start: datetime | None = None

    for segment in segments:
        if not current_dialogue:
            # Start new dialogue
            current_dialogue = [segment]
            dialogue_start = segment.abs_start
            continue

        last_segment = current_dialogue[-1]
        gap = segment.abs_start - last_segment.abs_end
        duration = segment.abs_end - dialogue_start

        # Check if we need to split
        should_split = False
        if gap > silence_gap:
            # Too much silence - end dialogue
            should_split = True
        elif duration > max_duration:
            # Dialogue too long - split at this point
            should_split = True

        if should_split:
            # Save current dialogue and start new one
            if current_dialogue:
                dialogues.append(current_dialogue)
            current_dialogue = [segment]
            dialogue_start = segment.abs_start
        else:
            current_dialogue.append(segment)

    # Don't forget the last dialogue
    if current_dialogue:
        dialogues.append(current_dialogue)

    return dialogues


async def process_chunk_dialogues(
    session: AsyncSession,
    chunk: dict[str, Any],
    speech_segments: list[tuple[int, int]],
) -> None:
    """
    Process speech segments from a chunk and build/update dialogues.

    Handles:
    - Continuation of open dialogues from previous chunks
    - Creation of new dialogues
    - Splitting long dialogues
    - Tracking open dialogue state for cross-chunk continuity
    """
    settings = get_settings()

    device_id = chunk["device_id"]
    point_id = chunk["point_id"]
    register_id = chunk["register_id"]
    chunk_id = chunk["chunk_id"]
    chunk_start_ts = chunk["start_ts"]
    chunk_end_ts = chunk["end_ts"]

    # Convert segments to absolute timestamps
    abs_segments = segments_to_absolute(chunk_id, chunk_start_ts, speech_segments)

    if not abs_segments:
        # No speech in this chunk - check if we need to close open dialogue
        state = await repository.get_device_dialogue_state(session, device_id)
        if state and state["open_dialogue_id"]:
            last_speech_end = state["last_speech_end_ts"]
            gap = chunk_end_ts - last_speech_end if last_speech_end else None

            if gap and gap.total_seconds() > settings.silence_gap_sec:
                # Close the open dialogue due to silence
                logger.info(
                    "Closing dialogue due to silence",
                    extra={"dialogue_id": str(state["open_dialogue_id"])},
                )
                await repository.upsert_device_dialogue_state(
                    session, device_id, None, None
                )
        return

    # Get or initialize device state
    state = await repository.get_device_dialogue_state(session, device_id)
    open_dialogue_id = state["open_dialogue_id"] if state else None
    last_speech_end_ts = state["last_speech_end_ts"] if state else None

    # Check if we should continue the open dialogue
    current_dialogue: DialogueInfo | None = None
    first_segment = abs_segments[0]

    if open_dialogue_id and last_speech_end_ts:
        gap = (first_segment.abs_start - last_speech_end_ts).total_seconds()

        if gap <= settings.silence_gap_sec:
            # Continue the open dialogue
            existing = await repository.get_dialogue_by_id(session, open_dialogue_id)
            if existing:
                current_dialogue = DialogueInfo(
                    dialogue_id=open_dialogue_id,
                    device_id=device_id,
                    point_id=point_id,
                    register_id=register_id,
                    start_ts=existing["start_ts"],
                    end_ts=existing["end_ts"],
                )
                logger.info(
                    "Continuing open dialogue",
                    extra={"dialogue_id": str(open_dialogue_id), "gap_sec": gap},
                )
        else:
            # Gap too large - close old dialogue, will create new one
            logger.info(
                "Closing dialogue due to gap",
                extra={"dialogue_id": str(open_dialogue_id), "gap_sec": gap},
            )
            open_dialogue_id = None

    # Process segments and build dialogues
    segments_to_process = abs_segments
    dialogues_to_save: list[DialogueInfo] = []

    # If we have a continuing dialogue, try to add segments to it
    if current_dialogue:
        # Check duration constraint
        for i, segment in enumerate(segments_to_process):
            duration = (segment.abs_end - current_dialogue.start_ts).total_seconds()

            if duration > settings.max_dialogue_sec:
                # Dialogue would be too long - save current and start fresh
                dialogues_to_save.append(current_dialogue)
                current_dialogue = None
                segments_to_process = segments_to_process[i:]
                break
            else:
                current_dialogue.segments.append(segment)
                current_dialogue.end_ts = segment.abs_end

        if current_dialogue and current_dialogue.segments:
            # Check if there's a gap within remaining segments
            remaining_start_idx = len(abs_segments) - len(segments_to_process)
            if remaining_start_idx > 0:
                segments_to_process = []

    # Build new dialogues from remaining segments
    if segments_to_process:
        dialogue_groups = build_dialogues_from_segments(
            segments_to_process,
            settings.silence_gap_sec,
            settings.max_dialogue_sec,
        )

        for group in dialogue_groups:
            if current_dialogue and not current_dialogue.segments:
                # Reuse the dialogue info structure
                current_dialogue.segments = group
                current_dialogue.start_ts = group[0].abs_start
                current_dialogue.end_ts = group[-1].abs_end
            else:
                # Create new dialogue info
                if current_dialogue and current_dialogue.segments:
                    dialogues_to_save.append(current_dialogue)

                current_dialogue = DialogueInfo(
                    dialogue_id=None,
                    device_id=device_id,
                    point_id=point_id,
                    register_id=register_id,
                    start_ts=group[0].abs_start,
                    end_ts=group[-1].abs_end,
                    segments=group,
                )

    # Determine which dialogues are complete and which are still open
    # The last dialogue might continue into the next chunk
    last_segment = abs_segments[-1]
    chunk_end_gap = (chunk_end_ts - last_segment.abs_end).total_seconds()

    if current_dialogue and current_dialogue.segments:
        if chunk_end_gap < settings.silence_gap_sec:
            # Dialogue might continue - keep it open
            # But still save/update it
            pass
        else:
            # Dialogue is complete
            dialogues_to_save.append(current_dialogue)
            current_dialogue = None

    # Save dialogues
    for dialogue_info in dialogues_to_save:
        await _save_dialogue(session, dialogue_info)

    # Handle the potentially open dialogue
    if current_dialogue and current_dialogue.segments:
        dialogue_id = await _save_dialogue(session, current_dialogue)
        await repository.upsert_device_dialogue_state(
            session,
            device_id,
            dialogue_id,
            current_dialogue.end_ts,
        )
    else:
        # No open dialogue
        await repository.upsert_device_dialogue_state(
            session,
            device_id,
            None,
            last_segment.abs_end,
        )


async def _save_dialogue(
    session: AsyncSession,
    dialogue_info: DialogueInfo,
) -> UUID:
    """Save or update a dialogue and its segments."""
    if dialogue_info.dialogue_id:
        # Update existing dialogue
        await repository.update_dialogue_end_ts(
            session,
            dialogue_info.dialogue_id,
            dialogue_info.end_ts,
        )
        dialogue_id = dialogue_info.dialogue_id
    else:
        # Create new dialogue
        dialogue_id = await repository.create_dialogue(
            session,
            dialogue_info.device_id,
            dialogue_info.point_id,
            dialogue_info.register_id,
            dialogue_info.start_ts,
            dialogue_info.end_ts,
        )

    # Save segment links
    for segment in dialogue_info.segments:
        await repository.add_dialogue_segment(
            session,
            dialogue_id,
            segment.chunk_id,
            segment.start_ms,
            segment.end_ms,
        )

    return dialogue_id
