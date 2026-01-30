"""Audio assembler - extracts and concatenates audio segments for ASR."""

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from pydub import AudioSegment

from .settings import get_settings

logger = logging.getLogger(__name__)


class AudioAssemblyError(Exception):
    """Error assembling audio for ASR."""
    pass


@dataclass
class SegmentInfo:
    """Information about a dialogue segment."""
    chunk_id: UUID
    chunk_path: Path
    start_ms: int
    end_ms: int


def extract_segment_wav(
    input_path: Path,
    start_ms: int,
    end_ms: int,
    output_path: Path,
) -> None:
    """
    Extract a segment from audio file and convert to WAV 16kHz mono.
    Uses ffmpeg for efficient processing.
    """
    start_sec = start_ms / 1000.0
    duration_sec = (end_ms - start_ms) / 1000.0

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-i", str(input_path),
        "-ar", "16000",
        "-ac", "1",
        "-f", "wav",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=60,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(
            "ffmpeg extraction failed",
            extra={
                "input": str(input_path),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "stderr": e.stderr.decode() if e.stderr else "",
            },
        )
        raise AudioAssemblyError(f"ffmpeg extraction failed: {e.stderr.decode() if e.stderr else str(e)}") from e
    except subprocess.TimeoutExpired as e:
        raise AudioAssemblyError(f"ffmpeg extraction timed out") from e


def assemble_dialogue_audio(
    segments: list[SegmentInfo],
) -> tuple[Path, float]:
    """
    Assemble all dialogue segments into a single WAV file.

    1. Extract each segment as WAV 16kHz mono
    2. Concatenate all segments
    3. Return path to assembled file and total duration in seconds

    Uses pydub for concatenation which handles format normalization.
    """
    settings = get_settings()
    work_dir = Path(settings.audio_tmp_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if not segments:
        raise AudioAssemblyError("No segments to assemble")

    # Extract each segment
    segment_paths: list[Path] = []
    combined = AudioSegment.empty()

    try:
        for i, seg in enumerate(segments):
            # Extract segment to temp wav
            seg_path = work_dir / f"seg_{i}_{seg.chunk_id}_{seg.start_ms}_{seg.end_ms}.wav"

            extract_segment_wav(
                input_path=seg.chunk_path,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                output_path=seg_path,
            )
            segment_paths.append(seg_path)

            # Load and append to combined audio
            audio_seg = AudioSegment.from_wav(str(seg_path))
            combined += audio_seg

        # Export combined audio
        output_path = work_dir / f"dialogue_combined_{segments[0].chunk_id}.wav"
        combined.export(str(output_path), format="wav")

        duration_sec = len(combined) / 1000.0

        logger.info(
            "Assembled dialogue audio",
            extra={
                "segments_count": len(segments),
                "duration_sec": round(duration_sec, 2),
                "output_path": str(output_path),
            },
        )

        return output_path, duration_sec

    finally:
        # Clean up segment files
        for path in segment_paths:
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass


def cleanup_assembled_audio(path: Path) -> None:
    """Remove assembled audio file."""
    try:
        if path.exists():
            path.unlink()
    except OSError as e:
        logger.warning(f"Failed to cleanup assembled audio {path}: {e}")


def prepare_dialogue_segments(
    db_segments: list[dict[str, Any]],
    chunk_paths: dict[UUID, Path],
) -> list[SegmentInfo]:
    """
    Prepare segment info from database records and fetched chunk paths.
    """
    result = []
    for seg in db_segments:
        chunk_id = seg["chunk_id"]
        if chunk_id not in chunk_paths:
            raise AudioAssemblyError(f"Missing chunk file for {chunk_id}")

        result.append(SegmentInfo(
            chunk_id=chunk_id,
            chunk_path=chunk_paths[chunk_id],
            start_ms=seg["start_ms"],
            end_ms=seg["end_ms"],
        ))

    return result
